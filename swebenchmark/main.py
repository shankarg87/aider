import argparse
from swebenchmark import utils
from swebenchmark.harness import process_instances
import random
import tempfile


def main():
    parser = argparse.ArgumentParser(description="Process some arguments.")
    parser.add_argument("run_id", type=str, help="run id")
    parser.add_argument("version", choices=["lite", "verified", "test"], help="which version of swe_bench to use")
    parser.add_argument("model_name_or_path", type=str, help="model name or path (optional argument)")
    parser.add_argument("--output_folder", type=str, default="", help="output folder")
    parser.add_argument("--select_random", type=int, default=0, help="select random number of instances (optional argument)")
    parser.add_argument("--instance_id", type=str, help="specific instance_id (optional argument)")
    parser.add_argument("--repo_path", type=str, help="pre-existing path to repo (optional argument)") # not widely used
    parser.add_argument("--num_tries", type=int, default=1, help="number of tries to run the model (optional argument)")
    parser.add_argument("--num_threads", type=int, default=1, help="number of threads")
    parser.add_argument("--use_oracle", action="store_true", help="use oracle")
    parser.add_argument("--gcs_bucket", type=str, help="gcs bucket (optional argument) to store results of the run")


    args = parser.parse_args()

    print(f"Version: {args.version}")
    print(f"Output Folder: {args.output_folder}")
    if args.model_name_or_path:
        print(f"Model Name or Path: {args.model_name_or_path}")
    if args.instance_id:
        print(f"Instance ID: {args.instance_id}")
    if args.repo_path:
        print(f"Repo Path: {args.repo_path}")

    dataset = None
    if args.version == "lite":
        dataset = utils.get_dataset(utils.LITE_DATASET, utils.LITE_DATASET_FNAME)
    elif args.version == "verified":
        dataset = utils.get_dataset(utils.VERIFIED_DATASET, utils.VERIFIED_DATASET_FNAME)
    elif args.version == "test":
        dataset = utils.get_dataset(utils.FULL_DATASET, utils.FULL_DATASET_FNAME)
    if args.select_random != 0:
        random_keys = random.sample(list(dataset.keys()), args.select_random)
        dataset = {key: dataset[key] for key in random_keys}        

    models = None
    output_folder = args
    if output_folder == "":
        output_folder = tempfile.mkdtemp(prefix=f"swebench.{args.run_id}")

    process_instances(
        run_id=args.run_id,
        dataset=dataset,
        model=args.model_name_or_path,
        instance_id=args.instance_id,
        num_tries=args.num_tries,
        threads=args.num_threads,
        output_folder=args.output_folder,
        use_oracle=args.use_oracle,
        gcs_bucket=args.gcs_bucket,
        temperature=0.0, # TODO: add temperature to the arguments
    )


if __name__ == "__main__":
    main()