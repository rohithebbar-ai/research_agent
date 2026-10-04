"""Review ideas from the terminal (until the API exists).

  python -m scripts.ideas_cli list [status]
  python -m scripts.ideas_cli approve IDEA_ID
  python -m scripts.ideas_cli reject IDEA_ID "reason"
"""
import sys

from tools.ideas import list_ideas, set_status


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "list"
    if cmd == "list":
        status = argv[2] if len(argv) > 2 else None
        for i in sorted(list_ideas(status), key=lambda i: i["created_at"]):
            print(f'{i["id"]}  [{i["status"]:9}] {i.get("kind", ""):9} {i.get("profile_topic", ""):22} {i["topic"]}')
            print(f'    why: {i.get("rationale", "")}')
    elif cmd == "approve":
        set_status(argv[2], "approved")
        print("approved", argv[2])
    elif cmd == "reject":
        set_status(argv[2], "rejected", reject_reason=argv[3] if len(argv) > 3 else None)
        print("rejected", argv[2])
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
