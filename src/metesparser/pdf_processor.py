"""PDF processing using OpenAI for OCR and extraction.

Uses OpenAI's API to extract text and legal descriptions from deed PDFs.
"""

import base64
import os
from pathlib import Path

import yaml
from openai import OpenAI

from .models import LegalDescription


class PDFProcessor:
    """Process PDF deeds and extract legal descriptions."""

    def __init__(self, api_key: str | None = None):
        """Initialize PDF processor.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not found. Set OPENAI_API_KEY environment variable.")

        self.client = OpenAI(api_key=self.api_key)
        self.prompts_dir = Path(__file__).parent.parent.parent / "prompts"

    def _load_prompt(self, prompt_name: str) -> dict:
        """Load a prompt from YAML file.

        Args:
            prompt_name: Name of prompt file (without .yaml extension)

        Returns:
            Dict with prompt configuration
        """
        prompt_path = self.prompts_dir / f"{prompt_name}.yaml"
        with open(prompt_path) as f:
            return yaml.safe_load(f)

    def _encode_pdf(self, pdf_path: str) -> str:
        """Encode PDF file to base64.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Base64-encoded PDF string
        """
        with open(pdf_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract all text from a PDF using OpenAI Responses API with GPT-4.1.

        Uses Responses API with base64-encoded PDF files.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Extracted text
        """
        # Load prompt
        prompt_config = self._load_prompt("extract_text_from_pdf")

        # Encode PDF to base64
        pdf_base64 = self._encode_pdf(pdf_path)
        filename = Path(pdf_path).name

        # Use Responses API with PDF file
        response = self.client.responses.create(
            model="gpt-4.1",
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "filename": filename,
                            "file_data": f"data:application/pdf;base64,{pdf_base64}",
                        },
                        {
                            "type": "input_text",
                            "text": prompt_config["user_prompt_template"],
                        },
                    ],
                },
            ],
        )

        return response.output_text or ""

    def extract_legal_description(self, pdf_path: str) -> str:
        """Extract legal description from a deed PDF.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Extracted legal description text
        """
        # First extract all text
        document_text = self.extract_text_from_pdf(pdf_path)

        # Load prompt
        prompt_config = self._load_prompt("extract_legal_description")

        # Build combined prompt with system and user content
        combined_prompt = f"{prompt_config['system_prompt']}\n\n{prompt_config['user_prompt_template'].format(document_text=document_text)}"

        response = self.client.responses.create(
            model="gpt-4.1",
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": combined_prompt,
                        },
                    ],
                },
            ],
        )

        return response.output_text or ""

    def normalize_legal_description(self, legal_desc_text: str) -> str:
        """Normalize and clean up legal description text.

        Args:
            legal_desc_text: Raw legal description text

        Returns:
            Normalized text
        """
        prompt_config = self._load_prompt("normalize_text")

        # Build combined prompt with system and user content
        user_prompt = prompt_config["user_prompt_template"].format(
            legal_description_text=legal_desc_text
        )
        combined_prompt = f"{prompt_config['system_prompt']}\n\n{user_prompt}"

        response = self.client.responses.create(
            model="gpt-4.1",
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": combined_prompt,
                        },
                    ],
                },
            ],
        )

        return response.output_text or ""

    def extract_calls_ai(self, legal_desc_text: str) -> list[dict]:
        """Extract calls using OpenAI (experimental).

        This is an AI-assisted approach. For production, consider using
        the rule-based CallExtractor for more reliability.

        Args:
            legal_desc_text: Normalized legal description text

        Returns:
            List of call dicts
        """
        import json

        prompt_config = self._load_prompt("extract_calls")

        # Build combined prompt with system and user content
        user_prompt = prompt_config["user_prompt_template"].format(
            legal_description_text=legal_desc_text
        )
        combined_prompt = f"{prompt_config['system_prompt']}\n\n{user_prompt}"

        response = self.client.responses.create(
            model="gpt-4.1",
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": combined_prompt,
                        },
                    ],
                },
            ],
        )

        result = json.loads(response.output_text or "{}")
        return result.get("calls", [])

    def process_deed_pdf(self, pdf_path: str) -> LegalDescription:
        """Process a deed PDF and return structured LegalDescription.

        This is the main entry point that orchestrates the full pipeline.

        Args:
            pdf_path: Path to PDF file

        Returns:
            LegalDescription object
        """
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

        # Build LegalDescription
        legal_desc = LegalDescription(
            poc_description=poc if poc else None,
            pob_description=pob,
            calls=calls,
            source_doc=Path(pdf_path).name,
            section=plss_data.get("section"),
            township=plss_data.get("township"),
            range=plss_data.get("range"),
            principal_meridian=plss_data.get("principal_meridian"),
            aliquot=plss_data.get("aliquot"),
        )

        print(f"Extracted {legal_desc.num_calls()} calls")

        return legal_desc
