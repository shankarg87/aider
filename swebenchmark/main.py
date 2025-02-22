import argparse
from swebenchmark import utils
from swebenchmark.harness import process_instances
import random
import tempfile
import os
import json


def parse_range(range_str):
    try:
        min_val, max_val = map(int, range_str.split('-'))
        return min_val, max_val
    except ValueError:
        raise argparse.ArgumentTypeError("Range must be in the format min-max")


def main():
    parser = argparse.ArgumentParser(description="Process some arguments.")
    parser.add_argument("--run_id", default="default", type=str, help="run id")
    parser.add_argument("--config_file", type=str, default="", help="path to a file containing additional arguments (optional)")    
    parser.add_argument("--version", choices=["lite", "verified", "test"], default="verified", help="which version of swe_bench to use")
    parser.add_argument("--model_name_or_path", type=str, default="openai/deepseek-chat", help="model name or path (optional argument)")
    parser.add_argument("--output_folder", type=str, default="", help="output folder")
    parser.add_argument("--select_random", type=int, default=0, help="select random number of instances (optional argument)")
    parser.add_argument("--select_range", type=str, help="select range of instances in the format min-max (optional argument)")
    parser.add_argument("--instance_id", type=str, help="specific instance_id (optional argument)")
    parser.add_argument("--repo_path", type=str, help="pre-existing path to repo (optional argument)") # not widely used
    parser.add_argument("--num_tries", type=int, default=1, help="number of tries to run the model (optional argument)")
    parser.add_argument("--num_threads", type=int, default=1, help="number of threads")
    parser.add_argument("--use_oracle", action="store_true", help="use oracle")
    parser.add_argument("--verbose", action="store_true", help="verbose logging")
    parser.add_argument("--use_search_coder", action="store_true", help="use search coder")   
    parser.add_argument("--gcs_bucket", type=str, help="gcs bucket (optional argument) to store results of the run")

    args = parser.parse_args()
    done_instances = []
    if args.config_file and os.path.exists(args.config_file):
        # Read extra arguments from the file
        with open(args.config_file, "r") as f:
            extra_args = f.read().split()
        # Parse them
        file_args = parser.parse_args(extra_args, namespace=argparse.Namespace())
        for k, v in vars(file_args).items():
            setattr(args, k, v)
        modified_model_name = args.model_name_or_path.replace("/", "_")
        out_pred_file = f"{args.output_folder}/results-{args.run_id}-{modified_model_name}.json"
        with open(out_pred_file, "w") as f:
            data = json.loads(f.read())
            done_instances = [d["instance_id"] for d in data]
        
    else:
        modified_model_name = args.model_name_or_path.replace("/", "_")
        in_pred_file = f"{args.output_folder}/run-{args.run_id}-{modified_model_name}.json"
        args_list = []
        for k, v in vars(args).items():
            if v is None:
                continue
            if isinstance(v, bool):
                if v:
                    args_list.append(f"--{k}")
            else:
                args_list.append(f"--{k}")
                args_list.append(str(v))
        with open(in_pred_file, "w") as f:
            f.write(" ".join(args_list))  

              
           


    print(f"Version: {args.version}")
    print(f"Output Folder: {args.output_folder}")
    if args.model_name_or_path:
        print(f"Model Name or Path: {args.model_name_or_path}")
    if args.instance_id:
        print(f"Instance ID: {args.instance_id}")
    if args.repo_path:
        print(f"Repo Path: {args.repo_path}")

    dataset = None

    min_val = 0
    max_val = 0

    if args.select_range is not None:
        min_val, max_val = parse_range(args.select_range)
        

    if args.version == "lite":
        dataset = utils.get_dataset(utils.LITE_DATASET, utils.LITE_DATASET_FNAME, min_val, max_val)
    elif args.version == "verified":
        dataset = utils.get_dataset(utils.VERIFIED_DATASET, utils.VERIFIED_DATASET_FNAME, min_val, max_val)
    elif args.version == "test":
        dataset = utils.get_dataset(utils.FULL_DATASET, utils.FULL_DATASET_FNAME, min_val, max_val)
    
    if args.select_random != 0:
        random_keys = random.sample(list(dataset.keys()), args.select_random)
        dataset = {key: dataset[key] for key in random_keys}


    models = None
    output_folder = args.output_folder
    if output_folder == "":
        output_folder = tempfile.mkdtemp(prefix=f"swebench.{args.run_id}")
    
    modified_model_name = args.model_name_or_path.replace("/", "_")
    out_pred_file = f"{output_folder}/results-{args.run_id}-{modified_model_name}.json"

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
        temperature=0.0, # TODO: add temperature to the arguments,
        verbose=args.verbose,
        use_search_coder=args.use_search_coder,
        out_pred_file=out_pred_file,
        done_instances=done_instances,
    )


if __name__ == "__main__":
    main()