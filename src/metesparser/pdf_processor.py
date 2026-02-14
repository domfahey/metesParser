"""PDF processing using pluggable LLM providers for OCR and extraction."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

from .llm_clients import BaseLLMClient, GeminiClient, LLMClientError, OpenAIClient
from .models import LegalDescription


class PDFProcessor:
    """Process PDF deeds and extract legal descriptions."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        provider: str | None = None,
        client: BaseLLMClient | None = None,
    ):
        """Initialize PDF processor with configurable LLM provider.

        Args:
            api_key: Optional API key override for the chosen provider
            provider: LLM provider name ("openai" or "gemini")
            client: Optional pre-constructed LLM client implementation
        """
        self._configured_api_key = api_key
        self.client = client or self._create_client(provider)
        self.prompts_dir = Path(__file__).parent.parent.parent / "prompts"

    def _load_prompt(self, prompt_name: str) -> dict[str, Any]:
        """Load a prompt from YAML file.

        Args:
            prompt_name: Name of prompt file (without .yaml extension)

        Returns:
            Dict with prompt configuration
        """
        prompt_path = self.prompts_dir / f"{prompt_name}.yaml"
        with open(prompt_path) as f:
            prompt_config = yaml.safe_load(f)

        if not isinstance(prompt_config, dict):
            raise ValueError(f"Prompt file '{prompt_name}' did not contain a mapping")

        return cast(dict[str, Any], prompt_config)

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract all text from a PDF using the configured LLM provider."""
        prompt_config = self._load_prompt("extract_text_from_pdf")
        prompt_text = prompt_config["user_prompt_template"]
        response_mime_type = prompt_config.get("response_mime_type")
        return self.client.generate_text_with_pdf(
            prompt_text, pdf_path, response_mime_type=response_mime_type
        )

    def extract_legal_description(self, pdf_path: str) -> str:
        """Extract legal description from a deed PDF."""
        document_text = self.extract_text_from_pdf(pdf_path)
        prompt_config = self._load_prompt("extract_legal_description")

        combined_prompt = f"{prompt_config['system_prompt']}\n\n{prompt_config['user_prompt_template'].format(document_text=document_text)}"
        return self.client.generate_text(combined_prompt)

    def normalize_legal_description(self, legal_desc_text: str) -> str:
        """Normalize and clean up legal description text."""
        prompt_config = self._load_prompt("normalize_text")

        user_prompt = prompt_config["user_prompt_template"].format(
            legal_description_text=legal_desc_text
        )
        combined_prompt = f"{prompt_config['system_prompt']}\n\n{user_prompt}"

        return self.client.generate_text(combined_prompt)

    def extract_calls_ai(self, legal_desc_text: str) -> list[dict[str, Any]]:
        """Extract calls using the configured LLM (experimental)."""
        prompt_config = self._load_prompt("extract_calls")

        user_prompt = prompt_config["user_prompt_template"].format(
            legal_description_text=legal_desc_text
        )
        combined_prompt = f"{prompt_config['system_prompt']}\n\n{user_prompt}"

        raw_response = self.client.generate_text(
            combined_prompt, response_mime_type="application/json"
        )

        try:
            result = json.loads(raw_response or "{}")
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise ValueError("LLM returned invalid JSON when extracting calls") from exc

        if not isinstance(result, dict):
            raise ValueError("LLM returned a non-object JSON payload for calls extraction")

        calls = result.get("calls", [])
        if not isinstance(calls, list):
            raise ValueError("LLM returned malformed calls payload (expected list)")

        return cast(list[dict[str, Any]], calls)

    def process_deed_pdf(self, pdf_path: str) -> LegalDescription:
        """Process a deed PDF and return structured LegalDescription."""
        from .call_extractor import CallExtractor
        from .text_parser import TextParser

        # Step 1: Extract legal description from PDF
        print("Extracting legal description from PDF...")
        legal_desc_text = self.extract_legal_description(pdf_path)

        # Step 2: Normalize text
        print("Normalizing text...")
        normalized_text = self.normalize_legal_description(legal_desc_text)

        # Step 3: Extract PLSS metadata
        print("Extracting PLSS metadata...")
        plss_data = TextParser.extract_plss_metadata(normalized_text)

        # Step 4: Extract POC and POB
        print("Extracting Point of Commencement and Point of Beginning...")
        poc, pob = TextParser.extract_poc_and_pob(normalized_text)

        # Step 5: Extract calls (using rule-based extractor for reliability)
        print("Extracting calls...")
        calls = CallExtractor.extract_calls(normalized_text)

        # Step 6: Enrich with azimuths
        calls = CallExtractor.enrich_calls_with_azimuths(calls)

        legal_desc = LegalDescription(
            poc_description=poc if poc else None,
            pob_description=pob,
            calls=calls,
            source_doc=Path(pdf_path).name,
            exhibit=None,
            page=None,
            survey_date=None,
            basis_of_bearing=None,
            datum=None,
            distance_unit="feet",
            section=plss_data.get("section"),
            township=plss_data.get("township"),
            range=plss_data.get("range"),
            principal_meridian=plss_data.get("principal_meridian"),
            aliquot=plss_data.get("aliquot"),
        )

        print(f"Extracted {legal_desc.num_calls()} calls")

        return legal_desc

    def _create_client(self, provider: str | None) -> BaseLLMClient:
        provider_name = (provider or os.getenv("METESPARSER_LLM_PROVIDER") or "openai").lower()

        try:
            if provider_name == "openai":
                return OpenAIClient(api_key=self._configured_api_key)
            if provider_name == "gemini":
                return GeminiClient(api_key=self._configured_api_key)
        except LLMClientError as exc:
            raise ValueError(str(exc)) from exc

        raise ValueError(
            f"Unsupported LLM provider '{provider_name}'. Choose from: openai, gemini."
        )
