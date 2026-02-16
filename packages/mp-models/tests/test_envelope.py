"""Verify JSONL envelope read/write."""
import io
import json


def test_write_and_read_raw_text():
    from mp_models.envelope import RawTextMessage, read_jsonl, write_jsonl

    msg = RawTextMessage(
        source="deed.pdf",
        text="BEGINNING at an iron pin",
        llm_provider="openai",
        llm_model="gpt-5",
    )
    buf = io.StringIO()
    write_jsonl(buf, msg)
    buf.seek(0)
    messages = list(read_jsonl(buf))
    assert len(messages) == 1
    assert messages[0].type == "raw_text"
    assert messages[0].source == "deed.pdf"


def test_discriminated_union_parsing():
    from mp_models.envelope import parse_message

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


def test_passthrough_fields():
    from mp_models.envelope import RawTextMessage

    msg = RawTextMessage(
        source="deed.pdf",
        text="hello",
        llm_provider="openai",
        llm_model="gpt-5",
        extracted_at="2026-02-16T14:30:00Z",
    )
    assert msg.llm_provider == "openai"
