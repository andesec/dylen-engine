# DLE learning selectors (user-facing)

Use **Blueprint** to pick the *learning outcome* (what you want to be able to do). Use **Implementation** to pick the *teaching route* (how it’s taught).

---

## Blueprints (dropdown labels)

| Blueprint                 | Student goal                        | Best when you want…                   | Broad topic areas (nouns)                                                                                                                   | Focus widgets                                                                    |
|---------------------------|-------------------------------------|---------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| **Procedural**            | “I can do this step-by-step.”       | Reliable execution and repetition     | Cooking fundamentals · Workplace tools · Study routines · Home maintenance · Keyboarding · Lab technique · Personal safety basics           | `ol`, `stepFlow`, `checklist`, `console` (sim), `codeviewer`, `table`, `success` |
| **Factual & Logical**     | “I understand why this is true.”    | Models, rules, cause/effect           | Physics · Biology · Economics · History · Linguistics · Mathematics · Political systems · Music theory                                      | `p`, `info`, `compare`, `table`, `asciiDiagram`, `flip`, `quiz`                  |
| **Social**                | “I can navigate this conversation.” | Better interpersonal outcomes         | Negotiation · Leadership · Dating & relationships · Teamwork · Parenting · Customer relations · Conflict resolution · Cross‑cultural norms  | `freeText`, `stepFlow`, `tip/warn`, `swipe`, `flip`, `quiz`                      |
| **Planning & Management** | “I can organize these resources.”   | Structure, sequencing, sustainability | Project management · Exam planning · Personal finance systems · Household systems · Travel planning · Event logistics · Business operations | `checklist`, `table`, `stepFlow`, `asciiDiagram`, `treeview`, `success`          |
| **Physical & Somatic**    | “My body has the muscle memory.”    | Technique, form, drills               | Strength training · Yoga · Dance · Swimming · Voice training · Instrument technique · Handwriting · Posture                                 | `ol`, `checklist`, `tip/warn`, `stepFlow`, `swipe`, `freeText`                   |
| **Values & Attitudes**    | “I value this perspective.”         | Reflection, ethics, worldview         | Ethics · Philosophy · Civic responsibility · Professional integrity · Media ethics · Sustainability · Cultural humility                     | `p`, `info`, `freeText`, `flip`, `swipe`, `quiz`                                 |
| **Metacognitive**         | “I know how to optimize my brain.”  | Learning how to learn                 | Memory systems · Focus · Habit formation · Bias awareness · Critical thinking · Note‑taking methods · Time management                       | `freeText`, `checklist`, `flip`, `tip`, `stepFlow`, `quiz`                       |
| **Critique & Analysis**   | “I can judge the quality of this.”  | Evaluation against standards          | News credibility · Research appraisal · Art criticism · Argument quality · Product reviews · Portfolio review · Data interpretation         | `compare`, `table`, `checklist`, `swipe`, `quiz`, `codeviewer`                   |
| **Creativity**            | “I can create something original.”  | Producing work under constraints      | Creative writing · Design · Curriculum · Music · Visual art · Storytelling · Business concepts                                              | `freeText`, `codeviewer`, `asciiDiagram`, `table`, `checklist`, `flip`           |
| **Strategy**              | “I can choose well with tradeoffs.” | Decisions under uncertainty           | Career strategy · Money strategy · Health strategy · Policy tradeoffs · Relationship decisions · Risk management · Opportunity costs        | `compare`, `swipe`, `stepFlow`, `table`, `checklist`, `quiz`, `asciiDiagram`     |

---

## Teaching Style (teaching route)

| Teaching Style  | What it means                        | Best for                       | Broad topic areas (nouns)                                                                                              | Focus widgets                                                                            |
|-----------------|--------------------------------------|--------------------------------|------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------|
| **Conceptual**  | Intuition + mental models            | Fast clarity and orientation   | Psychology basics · History overviews · Nutrition basics · Systems overviews · Intro philosophy · Big‑picture science  | `p`, `info`, `asciiDiagram`, `compare`, `flip`, `ul`                                     |
| **Theoretical** | Formal + precise understanding       | Correctness, rigor, edge cases | Grammar systems · Formal logic · Statistics · Constitutional law · Microeconomics · Chemistry fundamentals             | `p`, `table`, `compare`, `codeviewer`, `asciiDiagram`, `quiz`, `blank`                   |
| **Practical**   | Execution + application              | Getting results quickly        | Language practice · Fitness practice · Cooking practice · Public speaking practice · Study practice · Tool proficiency | `ol`, `stepFlow`, `checklist`, `console` (sim), `codeviewer`, `blank`, `success`, `quiz` |
| **All**         | Conceptual → Theoretical → Practical | Mastery, durable skill         | Personal finance · Language learning · Photography · Leadership development · Health & fitness · Academic subjects     | Mix of the above; end with `quiz` + `checklist` + (optional) `treeview`                  |

