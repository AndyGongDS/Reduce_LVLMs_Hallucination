from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from datasets import load_dataset
from PIL import Image
from tqdm import tqdm

from lvlm_models.base_lvlm import BaseLVLMModel


class ChainOfThoughtLVLM:
    def __init__(
        self,
        base_model: BaseLVLMModel,
        cot_prompt: str | None = None,
        answer_extraction_prompt: str = "FINAL ANSWER",
        cot_strategy: str = "visual_puzzle",
    ):
        """
        Chain of Thought wrapper for BaseLVLMModel.

        Args:
            base_model: The base BaseLVLMModel instance
            cot_prompt: Custom prompt to encourage step-by-step reasoning (if None, uses
            strategy-specific default)
            answer_extraction_prompt: Prompt to extract final answer
            cot_strategy: Strategy for chain of thought, options:
                          "basic", "detailed", "visual_puzzle", "yes_no_object"
        """
        self.model = base_model
        self.answer_extraction_prompt = answer_extraction_prompt
        self.cot_strategy = cot_strategy

        # Format string to encourage specific answer format
        self.answer_format_instruction = (
            "<response_format>\n"
            "Generate your answer in the following format:\n"
            "First, generate reasoning for each of the options, one line per option. "
            "Format your reasoning as follows:\n"
            "REASONING: [reasoning for each option, explaining why it is correct or incorrect]\n"
            "After completing your reasoning, please conclude with: FINAL ANSWER: [your answer]\n"
            "The final response must be just the letter of the correct option, no extra text "
            "or punctuation.\n"
            "</response_format>\n"
        )

        # Define strategy-specific prompts if not provided
        if cot_prompt is None:
            if cot_strategy == "basic":
                self.cot_prompt = (
                    "Let's think through this step by step:" + self.answer_format_instruction
                )
            elif cot_strategy == "detailed":
                self.cot_prompt = (
                    "<strategy>\n"
                    "Let's analyze this image carefully and answer the question step by step:\n"
                    "1. First, identify the main elements visible in the image.\n"
                    "2. Consider what the question is specifically asking about.\n"
                    "3. Examine relevant details in the image that relate to the question.\n"
                    "4. Draw logical connections between the visual elements and the question.\n"
                    "5. Formulate a clear and concise answer based on this analysis."
                    "</strategy>\n" + self.answer_format_instruction
                )
            elif cot_strategy == "visual_puzzle":
                self.cot_prompt = (
                    "<objective>\n"
                    "Given the puzzle presented in the image and the question below, select the "
                    "correct multiple choice option by responding with only one of the option's "
                    "letters: A, B, C or D\n"
                    "</objective>\n"
                    "<strategy>\n"
                    "Solve this visual puzzle by applying a systematic reasoning approach:\n\n"
                    "1. TESTING EACH OPTION:\n"
                    "   - Systematically test each multiple choice option against the identified "
                    "pattern/rule\n"
                    "   - Eliminate options that violate the pattern/rule\n"
                    "   - Confirm the correct option by verifying it completes the pattern/rule\n\n"
                    "2. FINAL VERIFICATION:\n"
                    "   - Double-check that the chosen answer is consistent with all observed "
                    "patterns\n"
                    "</strategy>\n" + self.answer_format_instruction
                )
            elif cot_strategy == "yes_no_object":
                self.cot_prompt = (
                    "<objective>\n"
                    "Determine whether the specific object mentioned in the question is present in "
                    "the image.\n"
                    "Answer with only 'YES' or 'NO'.\n"
                    "</objective>\n"
                    "<strategy>\n"
                    "Carefully analyze the image to determine if the object is present:\n\n"
                    "1. OBJECT IDENTIFICATION:\n"
                    "   - Look for the exact object mentioned in the question\n"
                    "   - Pay attention to the entire image, including foreground and background\n"
                    "   - Consider partially visible objects or objects that might be occluded\n\n"
                    "2. CAREFUL EXAMINATION:\n"
                    "   - Check for similar-looking objects that might be confused with the "
                    "target\n"
                    "   - Consider different perspectives, sizes, and variations of the object\n\n"
                    "3. VERIFICATION:\n"
                    "   - Confirm presence or absence with high confidence\n"
                    "   - Be conservative - only answer 'YES' if you're certain the object is "
                    "there\n"
                    "</strategy>\n" + self.answer_format_instruction
                )
            else:
                raise ValueError(f"Unknown CoT strategy: {cot_strategy}")
        else:
            # Append the answer format instruction to the custom prompt
            self.cot_prompt = cot_prompt + self.answer_format_instruction

    def generate_response_cot(
        self, image: Image.Image, question: str, options: Optional[List[str]] = None
    ) -> Tuple[str, str]:
        """
        Generate response using chain of thought reasoning.

        Args:
            image: Input image
            question: Question to answer
            options: Optional multiple choice options

        Returns:
            Tuple of (reasoning, final_answer)
        """
        cot_question = f"{self.cot_prompt}\n\n<QUESTION>\n{question}\n</QUESTION>"

        reasoning = self.model.generate_response(
            image=image,
            question=cot_question,
            options=options if self.cot_strategy == "visual_puzzle" else None,
            use_prefix_suffix=False,
        )

        final_answer = self._extract_answer(reasoning, options)

        return reasoning, final_answer

    def _extract_answer(self, reasoning: str, options: Optional[List[str]] = None) -> str:
        """
        Extract the final answer from the reasoning using a specific format.

        Args:
            reasoning: Full reasoning text
            options: Multiple choice options if available

        Returns:
            Extracted final answer
        """
        if "FINAL ANSWER:" in reasoning:
            answer_part = reasoning.split("FINAL ANSWER:")[-1].strip()
            if "." in answer_part:
                return answer_part.split(".")[0].strip()
            elif "\n" in answer_part:
                return answer_part.split("\n")[0].strip()
            else:
                return answer_part.strip()

        if options:
            option_values = (
                ["A", "B", "C", "D"] if self.cot_strategy == "visual_puzzle" else ["YES", "NO"]
            )
            for value in option_values:
                patterns = [
                    f"Option {value}",
                    f"option {value}",
                    f"({value})",
                    f"{value})",
                    f"answer is {value}",
                    f"answer is option {value}",
                    f"choose {value}",
                    f"select {value}",
                    f"answer: {value}",
                    f"Answer: {value}",
                    f"Answer: ({value})",
                ]
                for pattern in patterns:
                    if pattern in reasoning:
                        idx = option_values.index(value)
                        if idx < len(options):
                            return options[idx]

        sentences = reasoning.split(".")
        return sentences[-1].strip() if sentences else reasoning.strip()

    def generate_response_cot_batch(
        self,
        images: List[Image.Image],
        questions: List[str],
        options: Optional[List[List[str]]] = None,
    ) -> List[Tuple[str, str]]:
        """
        Generate responses for a batch of images and questions using chain of thought.

        Args:
            images: List of input images
            questions: List of questions to answer
            options: Optional list of multiple choice options for each question

        Returns:
            List of tuples containing (reasoning, final_answer) for each input
        """
        cot_questions = [f"{question}\n\n{self.cot_prompt}" for question in questions]

        reasonings = self.model.generate_response_batch(
            images=images,
            questions=cot_questions,
            options=options if self.cot_strategy == "visual_puzzle" else None,
            use_prefix_suffix=False,
        )

        results = []
        for i, reasoning in enumerate(reasonings):
            opts = options[i] if options is not None and i < len(options) else None
            final_answer = self._extract_answer(reasoning, opts)
            results.append((reasoning, final_answer))

        return results

    def evaluate_dataset_with_cot_batch(
        self,
        dataset_name: str,
        dataset_config: Optional[str] = None,
        split: str = "test",
        amount: int = 100,
        batch_size: int = 1,
        rand: bool = False,
        seed: int = 42,
        verbose: bool = False,
    ) -> pd.DataFrame:
        """
        Evaluate the model on a HuggingFace dataset using chain of thought.

        Args:
            dataset_name: HuggingFace dataset name
            dataset_config: Dataset configuration
            split: Dataset split to use
            amount: Number of examples to evaluate
            batch_size: Batch size for evaluation
            rand: Whether to shuffle the dataset
            seed: Random seed for shuffling
            verbose: Whether to print verbose output

        Returns:
            Dictionary with evaluation results
        """
        dataset = load_dataset(dataset_name, dataset_config, split=split)

        if rand:
            dataset = dataset.shuffle(seed=seed)
        dataset = dataset.select(range(min(amount, len(dataset))))

        images = dataset["image"]
        questions = dataset["question"]
        if "options" in dataset:
            options = dataset["options"]
        else:
            options = ["YES", "NO"] * len(dataset)
        answers = dataset["answer"]

        cot_results = []
        direct_results = []
        cot_responses = []
        direct_responses = []

        # Create progress bar
        pbar = tqdm(
            range(0, len(dataset), batch_size),
            desc="Evaluating with chain-of-thought (batch)",
            total=(len(dataset) + batch_size - 1) // batch_size,
        )

        for i in pbar:
            batch_end = min(i + batch_size, len(dataset))
            batch_images = images[i:batch_end]
            batch_questions = questions[i:batch_end]
            batch_options = (
                [options[j] for j in range(i, batch_end)] if options[0] is not None else None
            )
            batch_answers = [answers[j] for j in range(i, batch_end)]

            # Run with Chain of Thought
            try:
                batch_cot_responses = self.generate_response_cot_batch(
                    batch_images, batch_questions, batch_options
                )
            except Exception as e:
                print(f"Failed to generate CoT response for batch {i}: {questions}\n\n{e}\n")
                continue

            # Run without Chain of Thought (direct)
            try:
                batch_direct_responses = self.model.generate_response_batch(
                    images=batch_images,
                    questions=batch_questions,
                    options=batch_options,
                    use_prefix_suffix=True,
                )
            except Exception as e:
                print(f"Failed to generate CoT response for batch {i}: {questions}\n\n{e}\n")
                continue

            for j, ((reasoning, final_answer), direct_response) in enumerate(
                zip(batch_cot_responses, batch_direct_responses)
            ):
                correct_cot = self.match_multiple_choice_answer(
                    final_answer, batch_answers[j], batch_options
                )
                correct_direct = self.match_multiple_choice_answer(
                    direct_response, batch_answers[j], batch_options
                )

                cot_results.append(correct_cot)
                direct_results.append(correct_direct)
                cot_responses.append((reasoning, final_answer))
                direct_responses.append(direct_response)

                if verbose:
                    print(f"Question: {batch_questions[j]}")
                    print(f"CoT Reasoning: {reasoning}")
                    print(f"CoT Answer: {final_answer}")
                    print(f"Direct Answer: {direct_response}")
                    print(f"Correct CoT: {correct_cot}, Correct Direct: {correct_direct}\n")

                # Update progress bar postfix with current accuracies
                pbar.set_postfix(
                    {
                        "CoT Acc": f"{sum(cot_results) / len(cot_results):.3f}",
                        "Direct Acc": f"{sum(direct_results) / len(direct_results):.3f}",
                    }
                )

        cot_accuracy = sum(cot_results) / len(cot_results) if cot_results else 0
        direct_accuracy = sum(direct_results) / len(direct_results) if direct_results else 0
        print(f"CoT Accuracy: {cot_accuracy}")
        print(f"Direct Accuracy: {direct_accuracy}")

        return pd.DataFrame(
            {
                "question": questions,
                "answer": answers,
                "cot_reasoning": [cot_reasoning for cot_reasoning, _ in cot_responses],
                "cot_answer": [cot_answer for _, cot_answer in cot_responses],
                "direct_answer": direct_responses,
                "cot_correct": cot_results,
                "direct_correct": direct_results,
            }
        )

    def evaluate_dataset_with_cot(
        self,
        dataset_name: str,
        dataset_config: Optional[str] = None,
        split: str = "test",
        amount: int = 100,
        rand: bool = False,
        seed: int = 42,
        verbose: bool = False,
    ) -> pd.DataFrame:
        """
        Evaluate the model on a HuggingFace dataset using chain of thought.

        Args:
            dataset_name: HuggingFace dataset name
            dataset_config: Dataset configuration
            split: Dataset split to use
            amount: Number of examples to evaluate
            rand: Whether to shuffle the dataset
            seed: Random seed for shuffling
            verbose: Whether to print verbose output

        Returns:
            Dictionary with evaluation results
        """
        dataset = load_dataset(dataset_name, dataset_config, split=split)

        if rand:
            dataset = dataset.shuffle(seed=seed)
        dataset = dataset.select(range(min(amount, len(dataset))))

        images = dataset["image"]
        questions = dataset["question"]
        if "options" in dataset:
            options = dataset["options"]
        else:
            options = ["YES", "NO"] * len(dataset)
        answers = dataset["answer"]

        cot_results = []
        direct_results = []
        cot_responses = []
        direct_responses = []

        # Create progress bar
        pbar = tqdm(
            range(len(dataset)),
            desc="Evaluating with chain-of-thought",
            total=len(dataset),
        )

        for i in pbar:
            image = images[i]
            question = questions[i]
            option = options[i]
            answer = answers[i]
            # Run with Chain of Thought
            try:
                cot_reasoning, cot_answer = self.generate_response_cot(image, question, option)
            except Exception as e:
                print(f"Failed to generate CoT response for question {i}: {question}\n\n{e}\n")
                continue
            # Run without Chain of Thought (direct)
            try:
                direct_response = self.model.generate_response(
                    image=image, question=question, options=option, use_prefix_suffix=True
                )
            except Exception as e:
                print(f"Failed to generate direct response for question {i}: {question}\n\n{e}\n")
                continue

            correct_cot = self.match_multiple_choice_answer(cot_answer, answer, options)
            correct_direct = self.match_multiple_choice_answer(direct_response, answer, options)

            cot_results.append(correct_cot)
            direct_results.append(correct_direct)
            cot_responses.append((cot_reasoning, cot_answer))
            direct_responses.append(direct_response)

            if verbose:
                print(f"- Question: {question}")
                print(f"- CoT Reasoning:\n{cot_reasoning}")
                print(f"- Answer: {answer}")
                print(f"- CoT Answer: {cot_answer}")
                print(f"- Direct Answer: {direct_response}")
                print(f"- Correct? CoT: {correct_cot}, Direct: {correct_direct}")
                print("--------------------------------")

            # Update progress bar postfix with current accuracies
            pbar.set_postfix(
                {
                    "CoT Acc": f"{sum(cot_results) / len(cot_results):.3f}",
                    "Direct Acc": f"{sum(direct_results) / len(direct_results):.3f}",
                }
            )

        cot_accuracy = sum(cot_results) / len(cot_results) if cot_results else 0
        direct_accuracy = sum(direct_results) / len(direct_results) if direct_results else 0
        print("--------------------------------")
        print(f"CoT Accuracy: {cot_accuracy}")
        print(f"Direct Accuracy: {direct_accuracy}")
        if hasattr(self.model, "running_cost"):
            print(f"Total cost: {(self.model.running_cost):.6f} USD")
        print("--------------------------------")

        return pd.DataFrame(
            {
                "question": questions,
                "answer": answers,
                "cot_reasoning": [cot_reasoning for cot_reasoning, _ in cot_responses],
                "cot_answer": [cot_answer for _, cot_answer in cot_responses],
                "direct_answer": direct_responses,
                "cot_correct": cot_results,
                "direct_correct": direct_results,
            }
        )

    def compare_cot_vs_direct(
        self,
        image: Image.Image,
        question: str,
        options: Optional[List[str]] = None,
        answer: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Compare chain of thought reasoning with direct answering for a single question.

        Args:
            image: Input image
            question: Question to answer
            options: Optional multiple choice options
            answer: Optional ground truth answer for evaluation

        Returns:
            Dictionary with comparison results
        """
        # Get CoT response
        reasoning, final_answer = self.generate_response_cot(image, question, options)

        # Get direct response
        direct_response = self.model.generate_response(image, question, options)

        result = {
            "question": question,
            "cot_reasoning": reasoning,
            "cot_answer": final_answer,
            "direct_answer": direct_response,
        }

        if answer is not None:
            result["ground_truth"] = answer
            result["cot_correct"] = self.match_multiple_choice_answer(final_answer, answer, options)
            result["direct_correct"] = self.match_multiple_choice_answer(
                direct_response, answer, options
            )

        return result

    def match_multiple_choice_answer(
        self, model_answer: str, ground_truth: str, options: Optional[List[str]] = None
    ) -> bool:
        """
        Match a model's answer against ground truth for multiple choice questions.
        Supports both letter options (A, B, C, D) and YES/NO answers.

        Args:
            model_answer: The answer string from the model
            ground_truth: The ground truth answer (expected to be A, B, C, D or YES, NO)
            options: Optional list of valid options to check against

        Returns:
            True if the model's answer matches the ground truth
        """
        if not model_answer or not ground_truth:
            return False

        # Clean and normalize the answers
        model_clean = model_answer.strip().upper()
        gt_clean = ground_truth.strip().upper()

        # Direct match for simple YES/NO answers
        if gt_clean in ["YES", "NO"] and model_clean in ["YES", "NO"]:
            return gt_clean == model_clean

        # Determine valid options based on the ground truth or provided options
        valid_options = (
            options
            if options is not None
            else (["A", "B", "C", "D"] if gt_clean in ["A", "B", "C", "D"] else ["YES", "NO"])
        )

        if gt_clean not in valid_options:
            return False

        # Use regex to find clear indicators of chosen answers
        import re

        # Patterns that indicate a definitive answer choice
        patterns = [
            rf"(?:ANSWER|OPTION|CHOOSE|SELECT|FINAL ANSWER)[^\w]*(?:IS)?[^\w]*{gt_clean}\b",
            rf"\b{gt_clean}\)",
            rf"\({gt_clean}\)",
            rf"^{gt_clean}$",
        ]

        for pattern in patterns:
            if re.search(pattern, model_clean):
                return True

        # Look for the answer at the end of the response
        last_line = model_clean.split("\n")[-1].strip()
        if last_line == gt_clean:
            return True

        # If "FINAL ANSWER:" format is used
        if "FINAL ANSWER:" in model_clean:
            final_part = model_clean.split("FINAL ANSWER:")[-1].strip()

            # Create regex pattern based on valid options
            if "YES" in valid_options and "NO" in valid_options:
                words = re.findall(r"\b(YES|NO)\b", final_part)
            else:  # A, B, C, D options
                words = re.findall(r"\b[A-D]\b", final_part)

            return bool(words and words[0] == gt_clean)

        return False
