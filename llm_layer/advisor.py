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


# ═══════════════════════════════════════════════════════════════════════════
# CITIZEN QUERY — AI CHATBOT
# ═══════════════════════════════════════════════════════════════════════════

def answer_citizen_query(message, user_reports, cached_state):
    """
    Answer a citizen's natural-language complaint status query.
    Uses user's personal report history + live Pathway cached_state.
    Returns: {"answer": str, "speak": str (Hindi, <=2 sentences for TTS)}
    """
    gemini_key = os.getenv("GEMINI_API_KEY", "")

    # Enrich live dustbin state into each user report
    live_states = {}
    for ds in cached_state.get("dustbin_states", []):
        live_states[ds.get("dustbin_id", "")] = ds

    enriched_reports = []
    for r in (user_reports or []):
        did = r.get("dustbin_id", "")
        live = live_states.get(did, {})
        enriched_reports.append({
            **r,
            "current_state": live.get("state", "Unknown"),
            "current_report_count": live.get("report_count", 0),
        })

    if GEMINI_AVAILABLE and gemini_key:
        return _citizen_gemini(message, enriched_reports, cached_state, gemini_key)
    else:
        return _citizen_fallback(message, enriched_reports, cached_state)


def _citizen_gemini(message, enriched_reports, cached_state, api_key):
    """Call Gemini for citizen chatbot response."""
    try:
        from datetime import datetime
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Build user reports section
        reports_section = ""
        if enriched_reports:
            reports_section = "\nUSER'S REPORT HISTORY (most recent first):\n"
            for r in enriched_reports[:10]:
                reports_section += (
                    f"  - Dustbin {r.get('dustbin_id','?')} | "
                    f"Overflow Level: {r.get('overflow_level','?')} | "
                    f"Reported: {r.get('timestamp','?')[:16]} | "
                    f"Current State: {r.get('current_state','?')}\n"
                )
        else:
            reports_section = "\nUser has no previous reports on record.\n"

        # Build city context section
        ward_risks_list = cached_state.get("ward_risks", [])
        top_wards = sorted(ward_risks_list, key=lambda x: x.get("risk_score", 0), reverse=True)[:3]
        city_context = (
            f"City Waste Index: {cached_state.get('city_waste_index', 0)}/100 | "
            f"Rainfall: {cached_state.get('rainfall_mm_hr', 0)}mm/hr\n"
            f"Top Risk Wards: " +
            ", ".join(f"{w.get('name', w.get('ward_id','?'))} ({w.get('risk_score',0)}/100)" for w in top_wards)
        )

        prompt = f"""You are InfraWatch Nexus AI assistant for Delhi citizens.
Today: {now_str}

RULES:
- Answer in simple Hindi OR English based on the question language.
- Be conversational, empathetic, and specific to their data.
- Never say 'I don't know' — use the data to give a best answer.
- Keep answers under 3 sentences for voice readability.
- Always mention the current_state of their dustbin if relevant.

CITY STATUS:
{city_context}
{reports_section}
USER QUESTION: {message}

Respond ONLY in this JSON format:
{{"answer": "<response in user's language, max 3 sentences>", "speak": "<same in simple Hindi Devanagari, max 2 sentences, TTS friendly>"}}"""

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        text = response.text

        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end])
            return {
                "answer": parsed.get("answer", text[:300]),
                "speak": parsed.get("speak", parsed.get("answer", text[:150])),
            }
        return {"answer": text[:300], "speak": text[:150]}
    except Exception as e:
        return _citizen_fallback(message, enriched_reports, cached_state)


def _citizen_fallback(message, enriched_reports, cached_state):
    """Pattern-match fallback for citizen chatbot — no Gemini key needed."""
    msg_lower = message.lower()
    n = len(enriched_reports)
    waste_index = cached_state.get("city_waste_index", 0)

    if any(k in msg_lower for k in ["status", "report", "complaint", "shikayat", "mera"]):
        if enriched_reports:
            latest = enriched_reports[0]
            state = latest.get("current_state", "Unknown")
            did = latest.get("dustbin_id", "?")
            answer = (
                f"Your most recent report is for {did}. "
                f"Current status: {state}. "
                f"You have {n} total report(s) on record."
            )
            speak = f"आपकी शिकायत {did} के लिए दर्ज है। वर्तमान स्थिति: {state}।"
        else:
            answer = "No reports found on your account yet. Submit a report by scanning a dustbin QR code!"
            speak = "आपके खाते में कोई शिकायत नहीं मिली। कचरे के डिब्बे का QR स्कैन करके रिपोर्ट करें!"

    elif any(k in msg_lower for k in ["when", "kab", "kitne din", "time"]):
        priority = cached_state.get("priority_queue", [])
        if enriched_reports and priority:
            did = enriched_reports[0].get("dustbin_id", "")
            pos = next((i + 1 for i, p in enumerate(priority) if p.get("id") == did), None)
            if pos:
                answer = f"Your dustbin {did} is #{pos} in the collection priority queue. Expect collection soon."
                speak = f"आपका डिब्बा {did} प्राथमिकता सूची में #{pos} पर है।"
            else:
                answer = f"Your dustbin will be included in the next collection cycle."
                speak = "आपके डिब्बे की सफाई जल्द होगी।"
        else:
            answer = "Collection scheduling depends on ward priority. High overflow bins are cleared first."
            speak = "सफाई का समय वार्ड की प्राथमिकता पर निर्भर करता है।"

    elif any(k in msg_lower for k in ["ward", "area", "zone", "ilaka"]):
        ward_risks_list = cached_state.get("ward_risks", [])
        top = sorted(ward_risks_list, key=lambda x: x.get("risk_score", 0), reverse=True)[:3]
        if top:
            top_str = ", ".join(f"{w.get('name', w.get('ward_id','?'))} (risk: {w.get('risk_score', 0)})" for w in top)
            answer = f"Current high-risk areas: {top_str}. City waste index is {waste_index}/100."
            speak = f"उच्च जोखिम वाले क्षेत्र: {', '.join(w.get('name', w.get('ward_id','?')) for w in top[:2])}। शहर का अपशिष्ट सूचकांक {waste_index}/100 है।"
        else:
            answer = f"City waste index is currently {waste_index}/100."
            speak = f"शहर का अपशिष्ट सूचकांक {waste_index}/100 है।"

    else:
        answer = (
            f"Your {n} report(s) are being tracked by InfraWatch. "
            f"Current city waste index: {waste_index}/100. "
            "Ask me about your report status, collection timing, or area risk."
        )
        speak = f"आपकी {n} शिकायतें InfraWatch द्वारा ट्रैक की जा रही हैं। शहर का अपशिष्ट सूचकांक {waste_index}/100 है।"

    return {"answer": answer, "speak": speak}
