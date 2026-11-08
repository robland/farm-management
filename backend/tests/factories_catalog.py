"""Builders for crops, varieties and files.

Values are fictitious test data, not agronomic references.
"""

import io
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.crops.models import Crop
from apps.files.models import StoredFile
from apps.files.services import upload_file
from apps.organizations.access import resolve_org_context
from apps.organizations.models import Organization
from apps.users.models import User
from apps.varieties.models import TechnicalDataSet, Variety

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def pdf_upload(name: str = "fiche.pdf", content: bytes = PDF_BYTES) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="application/pdf")


def make_crop(org: Organization | None, name: str = "Culture test", **kwargs: Any) -> Crop:
    return Crop.objects.create(organization=org, common_name=name, **kwargs)


def make_variety(org: Organization, crop: Crop | None = None, **kwargs: Any) -> Variety:
    crop = crop or make_crop(org, name=f"Culture {Crop.objects.count() + 1}")
    return Variety.objects.create(
        organization=org, crop=crop, name=kwargs.pop("name", "Variété test"), **kwargs
    )


def make_sheet(org: Organization, admin: User) -> StoredFile:
    ctx = resolve_org_context(admin, org.id)
    stored, _ = upload_file(
        ctx,
        stream=io.BytesIO(PDF_BYTES),
        original_name="fiche.pdf",
        purpose=StoredFile.Purpose.TECHNICAL_SHEET,
    )
    return stored


def make_data_set(variety: Variety, number: int = 1) -> TechnicalDataSet:
    return TechnicalDataSet.objects.create(
        organization_id=variety.organization_id, variety=variety, version_number=number
    )
