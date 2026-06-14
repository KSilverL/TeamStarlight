import os
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from .schemas import BrandVideoProps

load_dotenv()

SYSTEM_PROMPT = """You are a brand strategist and creative director specialising in short-form social video.

Given a brand brief, produce structured data for a 12-second, 3-scene portrait video (9:16, 1080×1920).

## Scene breakdown
- Scene 1 — Brand identity: name, tagline, mood
- Scene 2 — Three key stats or product highlights
- Scene 3 — Call-to-action with headline, subtext, button label, contact

## Colour palette rules
- primaryColor: very dark (near black), sets the background mood, e.g. '#0d1117', '#1a0a0f'
- secondaryColor: the dominant brand colour — used for the logo, card borders, button gradient start
- accentColor: a complementary pop — used for lines, dots, button gradient end
- Colours must contrast strongly against each other and against white text
- Derive all three from the brand brief's industry, personality, and existing colours if mentioned

## Copy rules
- brandName: 1-2 words, ALL CAPS
- tagline: 3-6 words, no punctuation
- headline: 3-5 words, ends with '?'
- subtext: one sentence, max 12 words
- ctaLabel: action verb + 1-2 nouns, e.g. 'Start Free Trial', 'Book a Demo'
- contact: '@handle · domain.com' format
- stats: exactly 3 items — mix of numeric stats and a quality claim

Return only valid structured data — no explanation."""

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{brief}"),
])

llm = ChatAnthropic(
    model="claude-haiku-4-5-20251001",
    max_tokens=1024,
    temperature=1.0,
)

chain = prompt | llm.with_structured_output(BrandVideoProps)


def generate_brand_props(brief: str) -> BrandVideoProps:
    return chain.invoke({"brief": brief})
