from pathlib import Path

from ledgerline_api.graphql import schema
from ledgerline_api.service import content_fingerprint

REPO = Path(__file__).resolve().parents[3]


def test_same_text_with_different_whitespace_is_the_same_invoice():
    assert content_fingerprint(["ACME  GmbH\nTotal 46.41"], b"pdf-a") == content_fingerprint(
        ["ACME GmbH Total   46.41 "], b"pdf-b"
    )


def test_different_text_is_a_different_invoice():
    assert content_fingerprint(["Total 46.41"], b"x") != content_fingerprint(["Total 46.42"], b"x")


def test_scans_without_text_fall_back_to_file_bytes():
    # Every scan has empty text; hashing the text would make all scans duplicates of each other.
    assert content_fingerprint(["", "  "], b"scan-1") != content_fingerprint([""], b"scan-2")
    assert content_fingerprint(None, b"corrupt") == content_fingerprint([], b"corrupt")


def test_graphql_schema_file_matches_code():
    # Regenerate with `make codegen` when this fails.
    assert (REPO / "contracts" / "schema.graphql").read_text().strip() == schema.as_str().strip()
