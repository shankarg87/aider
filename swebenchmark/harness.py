#!/usr/bin/env python
import os
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

import lox
from aider.coders import Coder
from aider.io import InputOutput
from aider.models import Model, register_litellm_models
from aider.analytics import Analytics

from swebenchmark.dump import dump
from swebenchmark.utils import get_full_dataset  # noqa: F401
from swebenchmark.utils import get_lite_dataset  # noqa: F401
from swebenchmark.utils import get_devin_instance_ids, get_plausible, load_predictions, pick_winner

REPOS_DNAME = Path("repos")
CHAT_LOGS_DNAME = Path("chat-logs")
PREDS_DNAME = Path("predictions")


def diff_versus_commit(git_dname, commit):
    """
    Take a diff of `git_dname` current contents versus the `commit`.
    """

    diff_cmd = f"git -C {git_dname} diff {commit}"
    diff_output = subprocess.check_output(diff_cmd.split()).decode()
    return diff_output


def files_in_patch(patch):
    """
    Extract the list of modified files from a unified diff patch string.
    """
    files = []
    for line in patch.split("\n"):
        if line.startswith("--- a/") or line.startswith("+++ b/"):
            fname = line.split("/", 1)[1]
            if fname not in files:
                files.append(fname)
    return files


def checkout_repo(git_tempdir, entry):
    """
    Clone the SWE Bench entry's git `repo` into `dname` at the `base_commit`.
    Make a tempdir if no `dname` provided.
    """
    github_url = "https://github.com/"
    repo_url = github_url + entry["repo"]
    commit = entry["base_commit"]

    print(repo_url, commit)

    checkout_repo_url_commit(git_tempdir, repo_url, commit)


def checkout_repo_url_commit(repo_dname, url, commit):
    """
    Clone the git `url` into `dname` at `commit`.
    Check a local cache of the bare repo to avoid pulling from github every time.
    """

    # Extract repo name from URL
    repo_name = url.split("/")[-1].split(".")[0]
    repo_name += ".git"

    # dump(repo_name)
    REPOS_DNAME.mkdir(exist_ok=True)
    bare_repo = REPOS_DNAME / repo_name

    if not bare_repo.exists():
        cmd = f"git clone --bare {url} {bare_repo}"
        subprocess.run(cmd.split(), check=True)

    cmd = f"git clone {bare_repo} {repo_dname}"
    subprocess.run(cmd.split(), check=True)

    cmd = f"git -c advice.detachedHead=false -C {repo_dname} checkout {commit}"
    subprocess.run(cmd.split(), check=True)


def show_problems(dataset):
    """
    Print out all the instance_id and problem_descriptions.
    """
    for inst, entry in dataset.items():
        problem = entry["problem_statement"].splitlines()[0]
        print(f"{inst}: {problem}")


def run_pre_existing_tests(entry, git_dname):
    """Given the current contents of the `git_dname`, run the tests that
    were present in the entry's `repo` at the time of the
    `base_commit` or which have been added into the repo since.  This
    checks if the code in the `git_dname` has broken pre-existing
    tests or is failing any newly added tests.

    It does NOT attempt to run the tests in the `test_patch` which
    are used to evaluate whether the `model_patch` has resolved the
    `problem_statement`.

    Returns None if all the tests passed. Returns the text of the
    test run output if any failed.
    """
    pass
    
    """TODO: Code below is badly out of date, Need to fix """
    """
    model_patch = diff_versus_commit(git_dname, entry["base_commit"])
    passed, output = run_tests(
        entry,
        model_patch=model_patch,
        use_test_patch=False,
    )
    # We were UNABLE to run tests
    if passed is None:
        return

    if passed:
        return

    # Just keep the output after the (no-op) test patch applied,
    # which is the actual output from the tests that were run.
    output = output.split(">>>>> Applied Patch (test)")[-1]

    return output
    """


def get_coder(model, git_dname, chat_history_file, llm_history_file, event_history_file, test_cmd, temperature, oracle_files=None, suggest_shell_commands=False, verbose=False):
    """
    Get an instance of aider to work with the given LLM `model` at `temperature`
    on the code in `git_dname`. Will store the markdown chat logs in
    the `chat_history_file`. Tells aider it can use the `test_cmd` to
    run tests after the LLM edits files.

    If `oracle_files` are provided, they are added to the aider chat automatically.
    """
    if oracle_files and git_dname:
        oracle_files = [Path(git_dname) / fname for fname in oracle_files]

    model = Model(model)

    io = InputOutput(
        yes=True,  # Say yes to every suggestion aider makes
        chat_history_file=chat_history_file,  # Log the chat here
        input_history_file="/dev/null",  # Don't log the "user input"
        llm_history_file=llm_history_file, # Log the LLM completions here
    )
    dump(git_dname)

    coder = Coder.create(
        analytics=Analytics(logfile=event_history_file),
        edit_format="codesearch",
        main_model=model,
        io=io,
        map_tokens=2048,  # Use 2k tokens for the repo map
        stream=False,
        auto_commits=False,  # Don't bother git committing changes
        fnames=oracle_files,
        auto_test=False,  # TODO, need to fix this
        test_cmd=test_cmd,
        suggest_shell_commands=suggest_shell_commands,
    )
    coder.temperature = temperature

    # Take at most 4 steps before giving up.
    # Usually set to 5, but this reduces API costs.
    coder.max_reflections = 10

    # Add announcement lines to the markdown chat log
    coder.show_announcements()

    # messages = coder.format_messages()
    # utils.show_messages(messages)

    return coder


def process_one_instance(entry, num_tries, models, temperature, model_name_or_path, out_dname, out_pred_file, oracle=False, verbose=False):
    """Process one `entry` from SWE Bench using the LLM `models` at the
    given `temperature`.  Set `model_name_or_path` in the result json.
    Store the result json and the chat log into `out_dname`.
    """

    instance_id = entry["instance_id"]
    base_commit = entry["base_commit"]

    print("=" * 60)
    dump(instance_id)
    print("=" * 60)
    problem_statement = entry["problem_statement"]
    print(problem_statement)

    ###
    # DO NOT assist aider by telling it which files need to be modified!
    oracle = False
    gold_files = files_in_patch(entry["patch"])
    if oracle:
        oracle_files = gold_files
    else:
        oracle_files = None
    ###

    chat_history_file = Path(out_dname) / (instance_id + "-chat-history.md")
    llm_history_file = Path(out_dname) / (instance_id + "-llm-history.md")
    event_history_file = Path(out_dname) / (instance_id + "-event-history.json")

    # Clean up chat history from previous aborted run
    if chat_history_file.exists():
        chat_history_file.unlink()

    results = []
    cost = 0
    winner = None

    # Do NUM_TRIES tries for each of the models, until we find a *plausible* solution
    for attempt in range(1, num_tries + 1):
        for model in models:
            dump(attempt, model)
            
            with tempfile.TemporaryDirectory() as git_tempdir:
                dump(git_tempdir)
                checkout_repo(git_tempdir, entry) # TODO: cache this to run faster.
                # Cache the current working directory
                original_cwd = os.getcwd()
                os.chdir(git_tempdir)
                # Prepare the test command which will run the pre-existing tests
                #test_cmd = lambda: run_pre_existing_tests(entry, git_tempdir)  # noqa: E731
                test_cmd = None
                # Get an instance of aider
                coder = get_coder(
                    model,
                    git_tempdir,
                    chat_history_file,
                    llm_history_file,
                    event_history_file,
                    test_cmd,
                    temperature,
                    oracle_files=oracle_files,
                    suggest_shell_commands=False,
                    verbose=verbose,
                )

                dump(instance_id)
                dump(gold_files)

                # Tell aider to work on the `problem_statement`.
                # This is the same as if you pasted it into a fresh chat with aider
                # launched in the repo.
                message = """Below is a real GitHub issue from a popular GitHub repository.
The issue was filed some time ago.
The repo has been checked out at the commit that existed at the moment the issue was filed.
If you are already familiar with this repo, be cautious!
You are working with an old version of the repo!
Filenames, directory names, file contents, etc may be different than what you're used to.

Propose changes to update the repo to fix the problem below.

#"""
                message += problem_statement
                try:
                    coder.run(message)
                except Exception as coder_err:
                    # swallow any exceptions during benchmarking
                    dump(coder_err)
                    os.chdir(original_cwd)
                    continue
                
                print("Coder run is complete....")
                # Take note of which files aider added to the chat for stats later
                added_files = coder.get_inchat_relative_files()

                if not added_files:
                    print("No added files ....")
                    message = """You haven't named any files in this repo.
Remember, this repo is checked out at quite an old commit.
So the file layout and contents may be unfamiliar.

Tell me: which 3-5 files from this repo should I look at to solve the problem?
"""
                    coder.run(message)
                    print("Coder second run complete ....")

                dump(instance_id)
                dump(gold_files)
                dump(added_files)

                # Keep track of API costs
                cost += coder.total_cost

                # Get the diff between the current state and the original commit
                model_patch = diff_versus_commit(git_tempdir, base_commit)
                dump(model_patch)
                os.chdir(original_cwd)

            # Record the results for the logs
            result = dict(
                # Required args for running eval tests
                model_name_or_path=model_name_or_path,
                model_patch=model_patch,
                # For computing stats
                model=model,
                temperature=temperature,
                cost=coder.total_cost,
                added_files=added_files,
                gold_files=gold_files,
                edited_files=files_in_patch(model_patch),
                lint_outcome=coder.lint_outcome,
                test_outcome=coder.test_outcome,
            )
            result["try"] = attempt  # `try` is a python keyword
            result.update(entry)
            results.append(result)

            dump(result)

            # Did we get a successful edit, lint and test? If so, we found a plausible solution!
            if model_patch and coder.lint_outcome: # TODO, need to reincorporate test outcome // and coder.test_outcome:
                winner = result
                break

        # also break out of the attempts loop
        if winner:
            break

    # If there's no clear winner, look for the most viable result we got...
    if not winner:
        winner = pick_winner(results)

    if not winner:
        result = dict(
            # Required args for running eval tests
            instance_id=instance_id,
            model_name_or_path=model_name_or_path,
            model_patch=None,
        )

    dump(winner)
    if not winner:
        return

    print("\n\nFinal diff:\n")
    print(winner["model_patch"])

    # Avoid circular reference when we save to json
    winner = dict(winner)

    winner.update(
        dict(
            tries=attempt,
            all_results=results,  # Record all the results for later analysis
            cost=cost,  # total cost across all results
        )
    )

    # reformat in the way that swebench expects evaluation results
    if not out_pred_file:
        out_pred_file = Path(out_dname) / (instance_id + ".json")

    # Append the result to the json file specified in out_pred_file

    if Path(out_pred_file).exists():
        with open(out_pred_file, "r", encoding="utf-8") as f:
            all_results = json.load(f)
    else:
        all_results = []

    all_results.append(winner)

    with open(out_pred_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=4)

def export_to_gcs(output_folder, gcs_bucket):
    """ Exports data from the output folder to a GCS bucket
        May append to a single csv file with the summary results across all runs
    """    
    pass

def process_instances(
    dataset, model, instance_id, num_tries, threads, temperature, output_folder, run_id, use_oracle, gcs_bucket, verbose=False
):

    if not CHAT_LOGS_DNAME.exists():
        CHAT_LOGS_DNAME.mkdir()

    # No idea what the hell this code does
    chat_history_dname = CHAT_LOGS_DNAME / run_id
    chat_history_dname.mkdir(exist_ok=True)

    done_instances = []    
    if instance_id:
        remaining_instances = [instance_id]
    else:
        # TODO: fix this please
        remaining_instances = list(dataset.keys())

    if threads > 1:
        process_one_instance_lox = lox.process(threads)(process_one_instance)
        process_one_instance_func = process_one_instance_lox.scatter
        gather = process_one_instance_lox.gather
    else:
        process_one_instance_func = process_one_instance

    for instance_id in remaining_instances:
        if instance_id in done_instances:
            print("skipping", instance_id)
            continue

        process_one_instance_func(
            entry=dataset[instance_id],
            num_tries=num_tries,
            models=[model],
            temperature=temperature,
            model_name_or_path=model, # TODO: this may need to be fixed
            out_dname=output_folder,
            oracle=use_oracle,
            verbose=verbose,
            out_pred_file=f"{output_folder}/{run_id}"
        )

        print("#" * 60)
        # input()

    if threads > 1:
        gather()

    if gcs_bucket:
        export_to_gcs(output_folder, gcs_bucket)

def main():
    models_json = Path(".aider.models.json")
    if models_json.exists():
        print(f"Registering {models_json}")
        register_litellm_models([str(models_json)])

    #
    # Set the prefix to use in front of the predictions/ subdir name.
    #
    # prefix = "lite025"
    # prefix = "full-"
    # prefix = "full025-"
    prefix = "terse-udiff"

    #
    # Configure 1 or more models to use to try and find plausible solutions
    #
    # models = ["openrouter/deepseek/deepseek-chat"]
    # models = ["gpt-4o", "openrouter/anthropic/claude-3-opus"]
    # models = ["openrouter/anthropic/claude-3-opus"]
    # models = ["gpt-4o"]
    # models = ["gpt-4-1106-preview"]
    models = ["openrouter/anthropic/claude-3.5-sonnet"]
    # models = ["claude-3-5-sonnet-20240620"]

    # How many attempts per model to try and find a plausible solutions?
    num_tries = 1

    # What temperature to use during chat completions
    temperature = 0

    # Load the SWE Bench dataset
    # dataset = get_full_dataset()
    dataset = get_lite_dataset()

    just_devin_570 = False

    if just_devin_570:
        # Filter it to the Devin 570
        devin_insts = get_devin_instance_ids()
        dataset = dict((inst, entry) for inst, entry in dataset.items() if inst in devin_insts)

    #dataset = {"sympy__sympy-18532" : dataset["sympy__sympy-18532"]}

    # How many threads to use for attempting instances in parallel
    threads = 10

    # Any predictions/ dirs provided on the command line are treated
    # as earlier, higher priority runs.  If a plausible solution was
    # found for an instance already, we don't need to keep looking in
    # this run.
    prior_dnames = sys.argv[1:]

    process_instances(
        prefix, dataset, models, num_tries, temperature, threads, prior_dnames, just_devin_570
    )


if __name__ == "__main__":
    status = main()
    sys.exit(status)
