# inbox/ — the door between this project and the layer above it

This directory is the door, not a shelf. A message *to* `dojo` lands here; a
message *from* `dojo` is written into the receiver's own `inbox/`, never kept
here. The directory is tracked by git, so a message survives a change of
machine.

One file per message. The file name is `<YYYY-MM-DD>-<topic>.md`; the date is
the day it was written, not the day it was read.

## Shape of a file

Four header lines, then a blank line, then the body, then the effort.

```
kind:    contract | report | cost | direction | resource
from:    <agent name>
spend:   <class, not a number>
id:      <the message this answers, or `none — first contact`>
```

- `kind` sets the route. `contract` goes to the layer that wrote the contract.
  `cost` goes to whoever owns the commitment. `direction` goes to the person
  unchanged, carrying only the writer's own cost and priority rows.
  `resource` goes to whoever holds that budget.
- `spend` is one of `machine_time`, `money`, `person_time`,
  `person_attention`, `exclusive`, `irreversible`, `trust`. A message that
  asks for taste or costs someone carries its effort at the end of the same
  file; a `cost` report without effort is bounced with one line naming the gap.
- `id` is how a thread is followed. A reply names the file it answers.

## Bodies

- A report states the result, not the bookkeeping: what is now true, on what
  evidence, and the decision needed — which may be `none`. A report missing any
  of those three is not sent.
- A contract finding names the single field that could not be read and stops.
  It does not guess and it does not rewrite the contract.
- A question only the person can answer is forwarded, not answered.

## Reading and deleting

A message is read when this project next wakes, and after it is read its
content has landed — in the document that owns the decision, or as the work
actually done — and the file is deleted and committed. Deletion is tidying, not
a receipt. Git holds every deleted message at the commit that removed it.

## History

This directory was called `mail/` until 2026-10-21 and declared five header
lines (`from`, `to`, `kind`, `spend`, `id`). The `to` line is gone because the
directory the message sits in already says who reads it.
