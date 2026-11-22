import argparse
import sys

from . import config, pipeline, server, store


def show(job):
    v = pipeline.view(job)
    if not v:
        sys.exit("No such job.")
    print(f"job {job}: {v['job']['status']} {v['job']['message']}")
    p = v["packet"]
    if p:
        print(f"fund: {p['lab']['name']}, {p['lab']['institution']} ({p['decision']['confidence']} evidence)")
        for reason in p["decision"]["reasons"]:
            print(f"  - {reason}")
        for lab in p["backups"]:
            print(f"backup: {lab['name']}, {lab['institution']}")
        for check in p["checks"]:
            print(f"competitor {check['rival']}: {check['status']}")
        print(f"packet: {p['sha']}")
    c = v["cost"]
    print(f"cost: {c['credits']} credits (INR {c['inr']}), {c['calls']} calls, {c['tokens']} local tokens")


def main():
    config.load_env()
    store.init()
    ap = argparse.ArgumentParser(prog="patron")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8787)
    r = sub.add_parser("run")
    r.add_argument("request")
    r.add_argument("--fresh", action="store_true")
    for name in ("show", "retry"):
        sub.add_parser(name).add_argument("job")
    for name in ("approve", "reject"):
        a = sub.add_parser(name)
        a.add_argument("job")
        a.add_argument("--sha", required=True)
        a.add_argument("--by", required=True)
    sub.add_parser("resume")
    args = ap.parse_args()

    try:
        if args.cmd == "serve":
            return server.serve(args.port)
        if args.cmd == "resume":
            for job in pipeline.unfinished():
                pipeline.run(job)
                show(job)
            return
        if args.cmd == "run":
            job, duplicate = pipeline.submit(args.request, args.fresh)
            if duplicate:
                print("Same request as earlier today. Opening that job.")
            pipeline.run(job)
        else:
            job = args.job
            if args.cmd == "retry":
                pipeline.retry(job)
                pipeline.run(job)
            elif args.cmd in ("approve", "reject"):
                pipeline.review(job, args.cmd, args.sha, args.by)
                pipeline.run(job)
        show(job)
    except pipeline.Refused as err:
        sys.exit(str(err))


if __name__ == "__main__":
    main()
