from dataclasses import dataclass
from datasets import Dataset
from transformers import Wav2Vec2Processor
from typing import Dict, List, Optional, Union

import os
import pandas as pd
import torchaudio
import torch

#####
# Data Loading Function
#####
def speech_file_to_array_fn(batch, default_sr=16000):
    speech_array, sampling_rate = torchaudio.load(batch['path'])
    if sampling_rate != default_sr:
        resampler = torchaudio.transforms.Resample(sampling_rate, default_sr)
        speech_array = resampler(speech_array)
        sampling_rate = default_sr
    batch["speech_sample"] = speech_array[0].numpy()
    batch["sampling_rate"] = sampling_rate
    return batch

def load_dataset(manifest_file, num_proc, audio_column_name, text_column_name):
    base_path = '/'.join(manifest_file.split('/')[:-1])
    
    manifest_df = pd.read_csv(manifest_file)
    manifest_df['path'] = manifest_df[audio_column_name].apply(lambda path: os.path.join(base_path, path))
    batches = Dataset.from_pandas(manifest_df)
    batches = batches.map(speech_file_to_array_fn, num_proc=num_proc)
    return batches

#####
# Data Collator
#####
@dataclass
class DataCollatorCTCWithPadding:
    """
    Data collator that will dynamically pad the inputs received.
    Args:
        processor (:class:`~transformers.Wav2Vec2Processor`)
            The processor used for proccessing the data.
        padding (:obj:`bool`, :obj:`str` or :class:`~transformers.tokenization_utils_base.PaddingStrategy`, `optional`, defaults to :obj:`True`):
            Select a strategy to pad the returned sequences (according to the model's padding side and padding index)
            among:
            * :obj:`True` or :obj:`'longest'`: Pad to the longest sequence in the batch (or no padding if only a single
              sequence if provided).
            * :obj:`'max_length'`: Pad to a maximum length specified with the argument :obj:`max_length` or to the
              maximum acceptable input length for the model if that argument is not provided.
            * :obj:`False` or :obj:`'do_not_pad'` (default): No padding (i.e., can output a batch with sequences of
              different lengths).
        max_length (:obj:`int`, `optional`):
            Maximum length of the ``input_values`` of the returned list and optionally padding length (see above).
        max_length_labels (:obj:`int`, `optional`):
            Maximum length of the ``labels`` returned list and optionally padding length (see above).
        pad_to_multiple_of (:obj:`int`, `optional`):
            If set will pad the sequence to a multiple of the provided value.
            This is especially useful to enable the use of Tensor Cores on NVIDIA hardware with compute capability >=
            7.5 (Volta).
    """

    processor: Wav2Vec2Processor
    padding: Union[bool, str] = True
    max_length: Optional[int] = None
    max_length_labels: Optional[int] = None
    pad_to_multiple_of: Optional[int] = None
    pad_to_multiple_of_labels: Optional[int] = None

    def __call__(self, features: List[Dict[str, Union[List[int], torch.Tensor]]]) -> Dict[str, torch.Tensor]:
        # split inputs and labels since they have to be of different lenghts and need
        # different padding methods
        input_features = [{"input_values": feature["input_values"]} for feature in features]
        label_features = [{"input_ids": feature["labels"]} for feature in features]

        batch = self.processor.pad(
            input_features,
            padding=self.padding,
            max_length=self.max_length,
            pad_to_multiple_of=self.pad_to_multiple_of,
            return_tensors="pt",
        )
        with self.processor.as_target_processor():
            labels_batch = self.processor.pad(
                label_features,
                padding=self.padding,
                max_length=self.max_length_labels,
                pad_to_multiple_of=self.pad_to_multiple_of_labels,
                return_tensors="pt",
            )

        # replace padding with -100 to ignore loss correctly
        labels = labels_batch["input_ids"].masked_fill(labels_batch.attention_mask.ne(1), -100)
        batch["labels"] = labels

        return batch