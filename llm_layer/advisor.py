"""
InfraWatch — LLM Advisory Layer
Generates structured municipal advisories grounded in SOPs and segment data.
Supports Gemini/OpenAI with template fallback.
"""
import os
import json
from pathlib import Path

# Try to import LLM libraries
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from dotenv import load_dotenv
load_dotenv()

GUIDELINES_DIR = Path(__file__).parent / "guidelines"


def _load_guidelines():
    """Load all guideline documents as RAG context."""
    context = ""
    for md_file in GUIDELINES_DIR.glob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        context += f"\n--- {md_file.stem.upper()} ---\n{content}\n"
    return context


GUIDELINE_CONTEXT = _load_guidelines()


def generate_advisory(segment_data, question=None):
    """
    Generate a structured advisory for a road segment.
    
    Returns structured JSON:
    {
        urgency_level,
        recommended_action,
        justification,
        resource_required,
        estimated_response_time
    }
    """
    # Build the prompt
    prompt = _build_prompt(segment_data, question)
    
    # Try LLM providers
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")
    
    if GEMINI_AVAILABLE and gemini_key:
        return _call_gemini(prompt, gemini_key)
    elif OPENAI_AVAILABLE and openai_key:
        return _call_openai(prompt, openai_key)
    else:
        return _fallback_advisory(segment_data)


def _build_prompt(segment_data, question=None):
    """Build structured prompt for LLM."""
    seg = segment_data
    
    prompt = f"""You are InfraWatch AI, a municipal infrastructure risk advisor.

CONTEXT (Municipal SOPs & Guidelines):
{GUIDELINE_CONTEXT}

CURRENT SEGMENT DATA:
- Segment: {seg.get('name', 'Unknown')} ({seg.get('segment_id', '')})
- Zone: {seg.get('zone', '')}
- Road Type: {seg.get('road_type', '')}
- Risk Score: {seg.get('risk_score', 0)}/100
- State: {seg.get('state', 'Normal')}
- Condition: {seg.get('condition', 100)}/100
- Dominant Factor: {seg.get('dominant_factor', 'Unknown')}
- Permit Status: {seg.get('permit_status', 'none')}
- Metrics: {json.dumps(seg.get('metrics', {}), indent=2)}
- Prediction: {json.dumps(seg.get('prediction', {}), indent=2)}

{"USER QUESTION: " + question if question else "Generate a proactive advisory for this segment."}

RESPOND IN THIS EXACT JSON FORMAT:
{{
    "urgency_level": "P1/P2/P3/P4",
    "recommended_action": "specific action to take",
    "justification": "why this action is needed based on the data",
    "resource_required": "what resources are needed",
    "estimated_response_time": "time to deploy"
}}

Be specific. Reference actual data values. Do not be generic."""
    return prompt


def _call_gemini(prompt, api_key):
    """Call Gemini API."""
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        text = response.text
        # Try to parse JSON from response
        try:
            # Find JSON in response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
        return {"urgency_level": "P3", "recommended_action": text[:500], "justification": "LLM response", "resource_required": "TBD", "estimated_response_time": "TBD"}
    except Exception as e:
        return _fallback_advisory({})


def _call_openai(prompt, api_key):
    """Call OpenAI API."""
    try:
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        text = response.choices[0].message.content
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
        return {"urgency_level": "P3", "recommended_action": text[:500], "justification": "LLM response", "resource_required": "TBD", "estimated_response_time": "TBD"}
    except Exception as e:
        return _fallback_advisory({})


def _fallback_advisory(segment_data):
    """Template-based fallback when no LLM key is available."""
    score = segment_data.get("risk_score", 0)
    state = segment_data.get("state", "Normal")
    name = segment_data.get("name", "Unknown Segment")
    dominant = segment_data.get("dominant_factor", "General")
    condition = segment_data.get("condition", 100)
    metrics = segment_data.get("metrics", {})
    prediction = segment_data.get("prediction", {})
    
    if score >= 76:
        urgency = "P1"
        action = f"EMERGENCY: Deploy barricades and repair crew to {name} immediately. Dominant stress: {dominant}."
        response_time = "Within 2 hours"
        resource = "Emergency repair crew + barricades + traffic police"
    elif score >= 56:
        urgency = "P2"
        action = f"Schedule urgent inspection of {name}. {dominant} is the primary concern. Condition at {condition}/100."
        response_time = "Within 8 hours"
        resource = "Inspection team + repair materials"
    elif score >= 31:
        urgency = "P3"
        action = f"Monitor {name} closely. {dominant} showing elevated readings. Consider proactive maintenance."
        response_time = "Within 24 hours"
        resource = "Patrol team"
    else:
        urgency = "P4"
        action = f"{name} is within normal parameters. Continue routine monitoring."
        response_time = "Scheduled cycle"
        resource = "None — routine"
    
    justification = f"Risk score {score}/100 ({state}). "
    if metrics.get("report_count", 0) > 0:
        justification += f"{metrics['report_count']} citizen reports (avg severity {metrics.get('avg_severity', 0)}). "
    if metrics.get("rainfall_stress", 0) > 0:
        justification += f"Rainfall stress: {metrics['rainfall_stress']}. "
    if metrics.get("accident_score", 0) > 0:
        justification += f"Accident score: {metrics['accident_score']}. "
    
    if prediction and prediction.get("risk_delta_per_hr", 0) > 0:
        justification += f"PREDICTED: Risk may increase by {prediction['risk_delta_per_hr']} pts/hr."
    
    return {
        "urgency_level": urgency,
        "recommended_action": action,
        "justification": justification.strip(),
        "resource_required": resource,
        "estimated_response_time": response_time,
    }
