Write one cold outreach email. Plain text, no markdown, no bullet points.

HARD RULES
0. Everything you write must be about {account} itself. The facts below are already
   checked, but if any of them is about another company, ignore it.
1. Use only the verified facts and retrieved context below. If you assert anything
   that is not in them, you have fabricated a claim about a real company in a
   message that will be sent to a real person under someone's name. Do not.
2. Between 60 and 110 words in the body. Shorter is better.
3. Open on the specific fact. Never open with a greeting about how they are, never
   open with who you are.
4. Exactly one question, at the end.
5. At most one em dash in the whole email. Prefer a full stop.
6. Write the way a person types at their desk: short sentences, ordinary words,
   contractions. If a sentence would sound strange said out loud, rewrite it.

BANNED — do not use any of these or anything like them
  "I hope this email finds you well", "I wanted to reach out", "I'm reaching out",
  "just wanted to", "in today's fast-paced", "leverage", "utilize", "synergy",
  "seamless", "robust", "cutting-edge", "unlock", "delve", "landscape", "elevate",
  "empower", "streamline", "holistic", "not only ... but also", "furthermore",
  "moreover", "additionally", "that said".

INTENT — {intent_label}
{intent_guidance}

The ask: {intent_ask}

COMPANY
{account} (current signal band: {band})

VERIFIED FACTS — everything you say must trace to one of these
{facts}

RETRIEVED CONTEXT — background only, for tone and accuracy, not for new claims
{context}

WHO IS SENDING
Name: {sender_name}
Company: {sender_company}
What they do: {sender_offer}

Reply with a single JSON object and nothing else. No preamble, no explanation of
your choices, no notes about which rules you followed, no text before or after it:

{{"subject": "under 8 words", "body": "the email text only"}}

The body value is the email as it would be sent. It must not contain a subject
line, and it must not contain any commentary about the email.
