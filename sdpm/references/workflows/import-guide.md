# Import a guide — split someone else's rules into a structure and a writing guide

## Role

The user has a document of slide-making rules and wants it available to sdpm. You read
it, split its rules by which guide each one belongs to, save them, and report what you
could not take.

The split is the work. A document written for people usually mixes rules about the
argument, rules about wording and rules about appearance, because a person reading it
does not need them separated. sdpm does: a structure guide is read before the outline,
a writing guide before each slide's text, and appearance belongs to a style.

Read only the path the user gave you. Do not search for related files.

## Sorting each rule

Take the rules one at a time and apply these in order.

1. Is it about shape, colour or placement rather than the characters that get printed?
   That is design. Do not save it.
2. Can you tell whether one sentence breaks it, looking at that sentence alone? That is
   `writing`.
3. Does telling need a whole slide or more? That is `structure`.

The first step comes first because without it a rule about which shapes to use lands in
the structure guide, where nothing acts on it.

A rule you cannot place under any of the three does not belong to slides. Report it
rather than forcing it into one.

## Saving

Save each kind with `write_guide(kind, name, text)` through `run_style_python`.

- Give each file a kebab-case name you choose. Check both the bundled guides
  (`list_structures()`, `list_writings()`) and the user's own, and pick a name that
  collides with neither — a collision silently replaces the bundled default for every
  deck. The two kinds may share a name.
- Put a `description` in the frontmatter, one line saying what the guide decides. Do
  not put a `kind` key: the directory already says which kind it is.
- Write the rules as rules, in the user's language. Keep what the source means. Where
  the source argues for a rule at length, keep the rule and drop the argument.

## Reporting, and what to ask

Report four things:

- The two guides you saved, with their names and what each one covers.
- The design rules you found. Say that these belong in a style, not a guide, and that
  `start_style` is where a style is written.
- What you dropped, and why for each one. A media index, a document's own update
  policy, instructions addressed to an AI and scope tags that never reach a printed
  slide are not slide rules.
- If the source shipped code, what that code measures, in prose. Do not save it and do
  not run it: there is no path in sdpm that executes a third party's checker, and the
  cloud sandbox has no shell, so one would behave differently there than locally. Say
  whether any of it looks worth adding to sdpm's own checks as separate work.

Then ask whether to make either guide the default, and call `set_default(kind, name)`
for the ones the user says yes to. Until a default is set, the guides are available by
name but nothing uses them on its own.
