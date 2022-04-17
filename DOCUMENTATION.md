# Backup Modes
## SAVE
Write all files that are in source, but are not already existing in compare (in that version)
- source\compare: copy
- source&compare:
  - same: ignore
  - different: copy
- compare\source: ignore

## MIRROR
End up with a complete copy of source in compare
- source\compare: copy
- source&compare:
  - same: ignore
  - different: copy
- compare\source: delete

## HARDLINK
(Attention: here the source is compared against an older backup!)
End up with a complete copy of source in compare, but have hardlinks to already existing versions in other backups, if it exists
- source\compare: copy
  - same: hardlink to new backup from old backup
  - different: copy
- compare\source: ignore