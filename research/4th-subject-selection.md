# 4th Tutor Subject Selection

## Evaluation Criteria

1. Works with text-only exercises (no images/audio required)
2. Uses existing exercise types: code, text_input, multiple_choice, math_input, fill_in_blank
3. Benefits from Socratic questioning approach
4. No external dependencies (no API calls, no datasets)
5. Useful for both kids and adults

## Options Evaluated

| Subject | Text-only | Socratic fit | Exercise variety | Independence | Verdict |
|---------|-----------|-------------|------------------|--------------|---------|
| Logic & Critical Thinking | ✓ | Excellent | multiple_choice, text, fill_in | ✓ | **SELECTED** |
| Typing/Keyboard | ✗ (needs realtime) | Poor | Limited | ✓ | Rejected |
| Basic Science | ~ (hard without visuals) | Good | text, multiple_choice | ✓ | Deferred |
| Geography | ✓ | Poor (too factual) | multiple_choice, fill_in | ✓ | Rejected |
| Chess Puzzles | ~ (needs board) | Good | text notation | ✓ | Deferred |
| Creative Writing | ✓ | Excellent | text_input | ✓ | Alternative |

## Decision: Logic & Critical Thinking

### Why it works:
- **Socratic natural fit** — "Why does this conclusion follow?" / "What assumption are you making?" / "Can you find a counterexample?"
- **Rich exercise types** — pattern completion (fill_in_blank), identify fallacies (multiple_choice), construct arguments (text_input), truth tables (math_input)
- **Progressive difficulty** — basic patterns → deduction → induction → fallacies → argument analysis
- **No visuals needed** — all reasoning is verbal/symbolic
- **Universal appeal** — useful for students, programmers, professionals

### Proposed topic structure (5 levels):

**Level 1: Pattern Recognition**
- Number sequences
- Letter patterns
- Odd-one-out

**Level 2: Deductive Logic**
- If-then reasoning
- Syllogisms
- Contrapositive

**Level 3: Inductive Reasoning**
- Drawing conclusions from examples
- Analogies
- Generalizations and exceptions

**Level 4: Logical Fallacies**
- Ad hominem, straw man, false dichotomy
- Identify the fallacy in arguments
- Construct sound counter-arguments

**Level 5: Argument Analysis**
- Evaluate multi-step arguments
- Identify hidden assumptions
- Construct and defend positions

### Exercise examples:

```
Pattern: 2, 6, 18, 54, ?
Type: math_input
Answer: 162

Fallacy: "Everyone I know thinks this movie is good, therefore it must be good."
Type: multiple_choice
Options: [Ad populum, Ad hominem, False cause, Straw man]
Answer: Ad populum

Syllogism: All cats are animals. All animals breathe. Therefore: ___
Type: fill_in_blank
Answer: All cats breathe
```
