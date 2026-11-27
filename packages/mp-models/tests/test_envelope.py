"""Verify JSONL envelope read/write, passthrough fields, and blank-line handling."""

import io
import json

from mp_models.envelope import RawTextMessage, parse_message, read_jsonl, write_jsonl


def test_write_and_read_raw_text_skips_blank_lines():
    msg = RawTextMessage(
        source="deed.pdf",
        text="BEGINNING at an iron pin",
        llm_provider="openai",
        llm_model="gpt-5",
    )
    buf = io.StringIO()
    buf.write("\n   \n")
    write_jsonl(buf, msg)
    buf.write("\n")
    buf.seek(0)
    messages = list(read_jsonl(buf))
    assert len(messages) == 1
    assert messages[0].type == "raw_text"
    assert messages[0].source == "deed.pdf"


def test_discriminated_union_parsing():
    line = json.dumps(
        {
            "type": "raw_text",
            "source": "test.pdf",
            "text": "hello",
            "llm_provider": "openai",
            "llm_model": "gpt-5",
        }
    )
    msg = parse_message(line)
    assert msg.type == "raw_text"
    assert msg.text == "hello"


def test_passthrough_extra_fields_round_trip():
    msg = RawTextMessage(
        source="deed.pdf",
        text="hello",
        llm_provider="openai",
        llm_model="gpt-5",
        extracted_at="2026-02-16T14:30:00Z",
        custom_batch_id="batch-42",
    )
    assert msg.extracted_at == "2026-02-16T14:30:00Z"
    assert msg.model_extra == {"custom_batch_id": "batch-42"}

    buf = io.StringIO()
    write_jsonl(buf, msg)
    buf.seek(0)
    restored = list(read_jsonl(buf))[0]
    assert restored.model_extra == {"custom_batch_id": "batch-42"}
