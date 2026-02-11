Evaluate the following user response based on the provided instructions.

INSTRUCTIONS:
{{AI_PROMPT}}
{{WORDLIST_BLOCK}}
USER RESPONSE:
{{USER_TEXT}}

Return a structured evaluation in JSON format:
{
  "ok": true/false (if the response meets the core criteria),
  "issues": [list of specific problems found],
  "feedback": "constructive feedback for the user"
}
