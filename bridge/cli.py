"""Entry point: python -m bridge.cli <command> [arguments]."""
import argparse
import json
import sys
from pathlib import Path
from . import engine


def main(argv=None):
    ap=argparse.ArgumentParser(prog="langextract-sprite")
    sub=ap.add_subparsers(dest="command",required=True)
    create=sub.add_parser("create",help="create extraction job")
    create.add_argument("--data",help="inline JSON payload")
    create.add_argument("--file",help="UTF-8 JSON payload file")
    nxt=sub.add_parser("next",help="get unsubmitted prompts")
    nxt.add_argument("job_id")
    nxt.add_argument("--limit",type=int,default=3)
    submit=sub.add_parser("submit",help="submit structured inference responses")
    submit.add_argument("job_id")
    submit.add_argument("--data",help="inline JSON with batch_id,responses")
    submit.add_argument("--file",help="JSON response file")
    listing = sub.add_parser("list", help="list recoverable jobs without exposing document text")
    listing.add_argument("--limit", type=int, default=20)
    for name in ("status","result","audit"):
        cmd=sub.add_parser(name)
        cmd.add_argument("job_id")
    repair=sub.add_parser("repair")
    repair.add_argument("job_id")
    repair.add_argument("prompt_id")
    args=ap.parse_args(argv)
    try:
        if args.command=="create":
            obj=load_input(args)
            output=engine.create_job(obj)
        elif args.command=="list":
            output=engine.list_jobs(args.limit)
        elif args.command=="audit":
            output=engine.audit_job(args.job_id)
        elif args.command=="next":
            output=engine.next_batch(args.job_id,args.limit)
        elif args.command=="submit":
            obj=load_input(args)
            output=engine.submit_batch(args.job_id,obj["batch_id"],obj["responses"])
        elif args.command=="status":
            output=engine.get_status(args.job_id)
        elif args.command=="result":
            output=engine.get_result(args.job_id)
        else:
            output=engine.reset_prompt(args.job_id,args.prompt_id)
    except (engine.BridgeError,ValueError,KeyError,TypeError,FileNotFoundError) as exc:
        print(json.dumps({"error":str(exc),"type":type(exc).__name__}),file=sys.stderr)
        return 2
    print(json.dumps(output,ensure_ascii=False))
    return 0


def load_input(args):
    if bool(args.data)==bool(args.file):
        raise engine.BridgeError("provide exactly one of --data or --file")
    if args.file:
        path=Path(args.file).resolve()
        # Restrict file inputs to the configured state directory (including wheel installs).
        if not path.is_relative_to(engine.DATA / "inputs"):
            raise engine.BridgeError("--file must be under the configured data/inputs directory")
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(args.data)


if __name__=="__main__":
    raise SystemExit(main())
