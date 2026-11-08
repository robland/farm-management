import hashlib
import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.files.models import StoredFile
from apps.files.services import detect_mime
from tests.factories_catalog import JPEG_BYTES, PDF_BYTES, PNG_BYTES, make_sheet, pdf_upload

pytestmark = pytest.mark.django_db


def org_files(world):
    return f"/api/v1/organizations/{world.org_a.id}/files/"


def farm_files(farm):
    return f"/api/v1/farms/{farm.id}/files/"


def test_detect_mime_from_signature():
    assert detect_mime(PDF_BYTES[:16]) == "application/pdf"
    assert detect_mime(PNG_BYTES[:16]) == "image/png"
    assert detect_mime(JPEG_BYTES[:16]) == "image/jpeg"
    assert detect_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert detect_mime(b"MZ\x90\x00 executable") is None


def test_upload_technical_sheet_and_download(world, client_for):
    client = client_for(world.admin_a)
    response = client.post(
        org_files(world), {"purpose": "technical_sheet", "file": pdf_upload()}, format="multipart"
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["detected_mime"] == "application/pdf"
    assert body["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    stored = StoredFile.objects.get(id=body["id"])
    assert "fiche" not in stored.storage_key  # opaque key

    download = client.get(f"{org_files(world)}{body['id']}/download/")
    assert download.status_code == 200
    assert b"".join(download.streaming_content) == PDF_BYTES
    assert download["Cache-Control"] == "private, no-store"


def test_spoofed_extension_and_mime_are_rejected(world, client_for):
    fake = SimpleUploadedFile("virus.pdf", b"MZ\x90\x00not a pdf at all", "application/pdf")
    response = client_for(world.admin_a).post(
        org_files(world), {"purpose": "technical_sheet", "file": fake}, format="multipart"
    )
    assert response.status_code == 400
    assert "file" in response.json()["field_errors"]


def test_pdf_not_allowed_as_photo_and_size_limit(world, client_for):
    client = client_for(world.manager_a1)
    photo_pdf = client.post(
        farm_files(world.farm_a1),
        {"purpose": "task_photo", "file": pdf_upload()},
        format="multipart",
    )
    assert photo_pdf.status_code == 400
    big = SimpleUploadedFile("big.png", PNG_BYTES + b"\x00" * (1024 * 1024 + 1), "image/png")
    too_big = client.post(
        farm_files(world.farm_a1), {"purpose": "task_photo", "file": big}, format="multipart"
    )
    assert too_big.status_code == 400
    empty = SimpleUploadedFile("e.png", b"", "image/png")
    assert (
        client.post(
            farm_files(world.farm_a1), {"purpose": "task_photo", "file": empty}, format="multipart"
        ).status_code
        == 400
    )


def test_purpose_scope_is_enforced(world, client_for):
    client = client_for(world.admin_a)
    receipt_at_org = client.post(
        org_files(world), {"purpose": "receipt", "file": pdf_upload()}, format="multipart"
    )
    assert receipt_at_org.status_code == 400
    sheet_at_farm = client.post(
        farm_files(world.farm_a1),
        {"purpose": "technical_sheet", "file": pdf_upload()},
        format="multipart",
    )
    assert sheet_at_farm.status_code == 400


def test_upload_permission_depends_on_purpose(world, client_for):
    worker = client_for(world.worker_a1)
    photo = SimpleUploadedFile("p.jpg", JPEG_BYTES, "image/jpeg")
    assert (
        worker.post(
            farm_files(world.farm_a1), {"purpose": "task_photo", "file": photo}, format="multipart"
        ).status_code
        == 201
    )
    receipt = worker.post(
        farm_files(world.farm_a1), {"purpose": "receipt", "file": pdf_upload()}, format="multipart"
    )
    assert receipt.status_code == 403


def test_download_permission_depends_on_purpose(world, client_for):
    finance = client_for(world.finance_a1)
    uploaded = finance.post(
        farm_files(world.farm_a1), {"purpose": "receipt", "file": pdf_upload()}, format="multipart"
    ).json()
    url = f"{farm_files(world.farm_a1)}{uploaded['id']}/download/"
    assert finance.get(url).status_code == 200
    assert client_for(world.worker_a1).get(url).status_code == 403  # no finance.view


def test_file_of_other_farm_or_org_is_not_found(world, client_for):
    receipt = (
        client_for(world.admin_a)
        .post(
            farm_files(world.farm_a1),
            {"purpose": "receipt", "file": pdf_upload()},
            format="multipart",
        )
        .json()
    )
    # Same organization, other farm URL.
    assert (
        client_for(world.admin_a)
        .get(f"{farm_files(world.farm_a2)}{receipt['id']}/download/")
        .status_code
        == 404
    )
    sheet = make_sheet(world.org_a, world.admin_a)
    other_org = client_for(world.admin_b).get(
        f"/api/v1/organizations/{world.org_b.id}/files/{sheet.id}/download/"
    )
    assert other_org.status_code == 404
    # An org-level file is not reachable through a farm URL either.
    assert (
        client_for(world.admin_a).get(f"{farm_files(world.farm_a1)}{sheet.id}/").status_code == 404
    )


def test_offline_queued_upload_is_idempotent(world, client_for):
    client = client_for(world.worker_a1)
    file_id = str(uuid.uuid4())

    def send(content=JPEG_BYTES):
        return client.post(
            farm_files(world.farm_a1),
            {
                "id": file_id,
                "purpose": "task_photo",
                "file": SimpleUploadedFile("p.jpg", content, "image/jpeg"),
            },
            format="multipart",
        )

    assert send().status_code == 201
    assert send().status_code == 200
    assert StoredFile.objects.filter(id=file_id).count() == 1
    assert send(JPEG_BYTES + b"different").status_code == 409
