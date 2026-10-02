# Copyright 2026 Acysos S.L.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import io

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    from PyPDF2 import PdfFileReader as PdfReader
    from PyPDF2 import PdfFileWriter as PdfWriter
from odoo import fields, models


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    def _is_deca_report(self, report_ref):
        if isinstance(report_ref, str):
            return report_ref in (
                "l10n_es_deca_oca.report_deca",
                "l10n_es_deca_oca.action_report_deca",
            )
        return (
            self._get_report(report_ref).report_name == "l10n_es_deca_oca.report_deca"
        )

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        if not res_ids or not self._is_deca_report(report_ref):
            return super()._render_qweb_pdf(report_ref, res_ids, data)
        if isinstance(res_ids, int):
            res_ids = [res_ids]
        pickings = self.env["stock.picking"].browse(res_ids)
        pickings._check_deca_required_fields()
        if len(res_ids) == 1:
            picking = pickings[0]
            current_hash = picking._get_deca_hash()
        if picking.deca_version > 0 and picking.deca_content_hash == current_hash:
            # Return existing attachment
            attachment_name = f"DeCA - {picking.name} - v{picking.deca_version}.pdf"
            attachment = (
                self.env["ir.attachment"]
                .sudo()
                .search(
                    [
                        ("res_model", "=", "stock.picking"),
                        ("res_id", "=", picking.id),
                        ("name", "=", attachment_name),
                    ],
                    limit=1,
                )
            )
            if attachment:
                return attachment.raw, "pdf"
        # Generate the raw PDF via super
        content, ext = super()._render_qweb_pdf(report_ref, res_ids, data)
        if ext != "pdf" or content.startswith(b"<!DOC"):
            return content, ext
        # Metadata manipulation
        if not picking.deca_first_version_date:
            picking.sudo().deca_first_version_date = fields.Datetime.now()
        picking.sudo().write(
            {
                "deca_version": picking.deca_version + 1,
                "deca_content_hash": current_hash,
            }
        )
        reader = PdfReader(io.BytesIO(content))
        writer = PdfWriter()
        if hasattr(reader, "pages"):
            for page in reader.pages:
                if hasattr(writer, "add_page"):
                    writer.add_page(page)
                else:
                    writer.addPage(page)
        else:
            for i in range(reader.getNumPages()):
                writer.addPage(reader.getPage(i))
        try:
            metadata = reader.metadata or {}
        except AttributeError:
            metadata = reader.getDocumentInfo() or {}
        custom_metadata = dict(metadata)
        creation_date = picking.deca_first_version_date.strftime("D:%Y%m%d%H%M%SZ")
        mod_date = fields.Datetime.now().strftime("D:%Y%m%d%H%M%SZ")
        custom_metadata.update(
            {
                "/CreationDate": creation_date,
                "/ModDate": mod_date,
            }
        )
        try:
            writer.add_metadata(custom_metadata)
        except AttributeError:
            writer.addMetadata(custom_metadata)
        output = io.BytesIO()
        writer.write(output)
        final_content = output.getvalue()
        # Save as immutable version attachment
        attachment_name = f"DeCA - {picking.name} - v{picking.deca_version}.pdf"
        self.env["ir.attachment"].sudo().create(
            {
                "name": attachment_name,
                "type": "binary",
                "raw": final_content,
                "res_model": "stock.picking",
                "res_id": picking.id,
                "mimetype": "application/pdf",
            }
        )
        return final_content, ext
