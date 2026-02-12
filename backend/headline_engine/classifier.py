"""
Headline classification using LLM.

LLM is used ONLY here — for classifying macro headlines.
- temperature = 0 (deterministic)
- Strict JSON output
- Schema validation
- No narrative generation
"""
import os
import json
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("btc_macro.headline_engine")


def _load_llm_config() -> Dict:
    config_path = Path(__file__).parent.parent / "config" / "llm_config.json"
    with open(config_path, "r") as f:
        return json.load(f)


LLM_CONFIG = _load_llm_config()

# Expected output schema for validation
EXPECTED_KEYS = {"event_bias", "risk_impact", "confidence", "reason"}
VALID_BIASES = {"hawkish", "dovish", "neutral"}
VALID_IMPACTS = {"risk_on", "risk_off", "neutral"}


class HeadlineClassifier:
    """Classifies macro headlines using LLM with deterministic settings."""
    
    def __init__(self):
        self.config = LLM_CONFIG["headline_classification"]
        self.prompt_template = LLM_CONFIG["headline_prompt_template"]
        self.prompt_version = self.config["prompt_version"]
        self.model = self.config["model"]
        self.client = self._init_client()
    
    def _init_client(self):
        """Initialize OpenAI client. Falls back to available LLM."""
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            try:
                from openai import OpenAI
                return OpenAI(api_key=openai_key)
            except ImportError:
                raise ImportError("openai package required. pip install openai")
        
        gemini_key = os.getenv("GEMINI_API_KEY")
        if gemini_key:
            # Return a marker so classify_single knows to use Gemini
            return {"type": "gemini", "api_key": gemini_key}
        
        raise ValueError(
            "No LLM API key found. Set OPENAI_API_KEY or GEMINI_API_KEY in .env"
        )
    
    def classify_headlines(self, headlines: List[Dict]) -> List[Dict[str, Any]]:
        """
        Classify a batch of headlines.
        
        Args:
            headlines: List of dicts with 'title' and 'description'
        
        Returns:
            List of classification dicts, each with:
                event_bias, risk_impact, confidence, reason, _headline_title, _raw_response
        """
        results = []
        for h in headlines:
            try:
                classification = self.classify_single(
                    h.get("title", ""),
                    h.get("description", "")
                )
                classification["_headline_title"] = h.get("title", "")
                results.append(classification)
            except Exception as e:
                logger.warning(f"Failed to classify headline: {h.get('title', '')[:60]}... Error: {e}")
                # Return a neutral fallback — do NOT crash
                results.append({
                    "event_bias": "neutral",
                    "risk_impact": "neutral",
                    "confidence": 0.0,
                    "reason": f"Classification failed: {str(e)}",
                    "_headline_title": h.get("title", ""),
                    "_error": str(e),
                })
        
        return results
    
    def classify_single(self, headline: str, description: str) -> Dict[str, Any]:
        """
        Classify a single headline.
        
        Returns validated dict with: event_bias, risk_impact, confidence, reason
        """
        prompt = self.prompt_template.format(
            headline=headline.replace('"', "'"),
            description=(description or "").replace('"', "'")[:300],
        )
        
        if isinstance(self.client, dict) and self.client.get("type") == "gemini":
            raw = self._call_gemini(prompt)
        else:
            raw = self._call_openai(prompt)
        
        # Parse and validate JSON
        parsed = self._parse_json_response(raw)
        validated = self._validate_output(parsed)
        validated["_raw_response"] = raw
        validated["_model"] = self.model
        validated["_prompt_version"] = self.prompt_version
        
        return validated
    
    def _call_openai(self, prompt: str) -> str:
        """Call OpenAI API with temperature=0."""
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            max_tokens=self.config["max_tokens"],
            messages=[
                {"role": "system", "content": "You are a macro-economic event classifier. Output only valid JSON."},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content.strip()
    
    def _call_gemini(self, prompt: str) -> str:
        """Call Gemini API with temperature=0."""
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.client["api_key"])
            model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0,
                    max_output_tokens=self.config["max_tokens"],
                )
            )
            return response.text.strip()
        except ImportError:
            raise ImportError("google-generativeai package required for Gemini. pip install google-generativeai")
    
    def _parse_json_response(self, raw: str) -> Dict:
        """Parse JSON from LLM response, handling markdown fences."""
        text = raw.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned invalid JSON: {e}. Raw: {raw[:200]}")
    
    def _validate_output(self, parsed: Dict) -> Dict:
        """Validate parsed output against expected schema."""
        # Check required keys
        missing = EXPECTED_KEYS - set(parsed.keys())
        if missing:
            raise ValueError(f"Missing keys in LLM output: {missing}")
        
        # Validate enum values
        if parsed["event_bias"] not in VALID_BIASES:
            parsed["event_bias"] = "neutral"
            logger.warning(f"Invalid event_bias, defaulted to neutral")
        
        if parsed["risk_impact"] not in VALID_IMPACTS:
            parsed["risk_impact"] = "neutral"
            logger.warning(f"Invalid risk_impact, defaulted to neutral")
        
        # Validate confidence range
        conf = parsed.get("confidence", 0)
        if not isinstance(conf, (int, float)):
            conf = 0.0
        parsed["confidence"] = max(0.0, min(1.0, float(conf)))
        
        # Validate reason is string
        if not isinstance(parsed.get("reason"), str):
            parsed["reason"] = str(parsed.get("reason", ""))
        
        return parsed
