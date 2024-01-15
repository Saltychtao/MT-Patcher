from functools import partial
from transformers import default_data_collator
from datasets import load_dataset
from torch.utils.data import DataLoader
from accelerate import Accelerator
import torch
from typing import Any, Callable, Dict, List, NewType, Optional, Tuple, Union,Sequence
InputDataClass = NewType("InputDataClass", Any)
from collections.abc import Mapping
import numpy as np
import transformers

from dataclasses import dataclass, field

@dataclass
class DataCollatorForAssessmentDataset(object):
    """Collate examples for supervised fine-tuning."""

    tokenizer: transformers.PreTrainedTokenizer

    def __call__(self, instances: Sequence[Dict]) -> Dict[str, torch.Tensor]:
        return_dict = {}
        for key in ("examples", "examples_labels"):
            if key not in instances[0]:
                continue
            entry = [torch.tensor(instance[key]).long() for instance in instances]
            data = torch.nn.utils.rnn.pad_sequence(
            entry, batch_first=True, padding_value=self.tokenizer.pad_token_id)
            if "labels" in key:
                data[data.eq(self.tokenizer.pad_token_id)] = -100
            return_dict[key] = data

        return return_dict

def preprocess(data_args,tokenizer,examples):
    prompt = data_args.prompt
    sources = examples["src_text"]
    translations = examples["bad_translation"]
    explanations = examples["explanations"]

    prefixes = [prompt.replace("<srctext>",src).replace("<tgttext>",tgt) for src,tgt in (sources,translations)]

    responses = []
    for explanation in explanations:
        res = []
        for e in explanation:
            res += "Type: {}; Severity: {}; Reason: {}\n".format(e["type"],e["severity"],e["reason"])
        responses.append(res)

    prefix_inputs = tokenizer(prefixes,padding="do_not_pad",truncation=True,max_length=256)
    
    responses_inputs = tokenizer(responses, max_length=256, padding="do_not_pad",truncation=True)

    examples = [
        torch.tensor(s+t + [tokenizer.eos_token_id]).long() for s,t in zip(prefix_inputs['input_ids'],responses_inputs['input_ids'])
    ]
    examples_labels = [
        torch.tensor([-100] * len(s) + t + [tokenizer.eos_token_id]).long() for s,t in zip(prefix_inputs['input_ids'],responses_inputs['input_ids'])
    ]
    
    return {
        "input_ids": examples,
        "labels": examples_labels,
}

def make_feedback_data_module(data_args,model_args,tokenizer):
    preprocess_function = partial(preprocess,data_args,tokenizer)
    data_files = {}
    dataset_args = {}
    if data_args.train_file is not None:
        data_files["train"] = data_args.train_file
    if data_args.validation_file is not None:
        data_files["validation"] = data_args.validation_file
    extension = data_args.train_file.split(".")[-1]
    raw_datasets = load_dataset(extension, data_files=data_files, **dataset_args)
    column_names = raw_datasets["train"].column_names

    tokenized_datasets = raw_datasets.map(
        preprocess_function,
        batched=True,
        num_proc=12,
        remove_columns=column_names,
        load_from_cache_file=False,
        desc="Running tokenizer on dataset",
    )
    train_dataset = tokenized_datasets["train"]
    data_collator = DataCollatorForAssessmentDataset(tokenizer=tokenizer)

    return dict(train_dataset=train_dataset, eval_dataset=None, data_collator=data_collator)


if __name__ == "__main__":
    import argparse
    from transformers import AutoTokenizer
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-file")
    parser.add_argument("--validation-file")
    parser.add_argument("--prompt",default="<srctext> [PLHD95] 请翻译成英文. ")
    parser.add_argument("--srclang", default="Chinese")
    parser.add_argument("--tgtlang", default="English")
    parser.add_argument("--model-dir")
    parser.add_argument("--preprocessing-num-workers",default=1)
    parser.add_argument("--overwrite-cache",default=True)
    parser.add_argument("--per-device-train-batch-size",default=20,type=int)
    parser.add_argument("--per-device-eval-batch-size",default=20,type=int)


    args = parser.parse_args()

    tokenizer = AutoTokenizer.from_pretrained(args.model_dir)
    accelerator = Accelerator()
    data_module = make_feedback_data_module(args,tokenizer,accelerator)

    for batch in data_module["train_dataloader"]:
        import pdb; pdb.set_trace()