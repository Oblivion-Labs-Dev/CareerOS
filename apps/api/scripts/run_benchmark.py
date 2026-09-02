"""CLI runner for CareerOS LLM Benchmark."""

import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.services.application_assistant.benchmark_suite import run_full_sequential_benchmark

async def main():
    gemini_key = os.environ.get("GEMINI_API_KEY") or settings.gemini_api_key
    
    # Sequential list of models:
    # 1. qwen2.5:3b (Local Model A) -> unload
    # 2. qwen3:4b (Local Model B) -> unload
    # 3. gemma3:12b (Local Model C) -> unload
    # 4. mistral-small3.2:24b (Local Model D) -> unload
    # 5. gemini-3.6-flash (Gemini API)
    models = [
        {"model": "qwen2.5:3b", "provider": "ollama"},
        {"model": "qwen3:4b", "provider": "ollama"},
        {"model": "gemma3:12b", "provider": "ollama"},
        {"model": "mistral-small3.2:24b", "provider": "ollama"},
        {"model": "gemini-3.6-flash", "provider": "gemini"},
    ]

    print("Starting CareerOS LLM Benchmark Suite...", flush=True)
    print(f"Testing {len(models)} models across 40 ground truth test cases sequentially.\n", flush=True)

    results = await run_full_sequential_benchmark(
        gemini_api_key=gemini_key,
        models_to_test=models,
        output_path="data/benchmark_results.json",
    )

    print("\n=======================================================", flush=True)
    print("CAREEROS BENCHMARK FINAL SCORECARD & LEADERBOARD", flush=True)
    print("=======================================================\n", flush=True)

    header = f"{'Model':<22} | {'Provider':<8} | {'Class Acc':<10} | {'Ans Acc':<9} | {'Crit Acc':<9} | {'Halluc':<8} | {'Abstain':<8} | {'Score':<7} | {'Verified Badge'}"
    print(header, flush=True)
    print("-" * len(header), flush=True)

    for item in results["leaderboard"]:
        row = (
            f"{item['model']:<22} | "
            f"{item['provider']:<8} | "
            f"{item['classificationAccuracy']:>9.1f}% | "
            f"{item['answerAccuracy']:>8.1f}% | "
            f"{item['criticalFieldAccuracy']:>8.1f}% | "
            f"{item['hallucinationRate']:>7.1f}% | "
            f"{item['correctAbstentionRate']:>7.1f}% | "
            f"{item['overallBenchmarkScore']:>6.1f}% | "
            f"{item['verifiedBadgePercent']}% verified"
        )
        print(row, flush=True)

    print("\n=======================================================", flush=True)
    print("RECOMMENDATIONS & COST PROJECTIONS", flush=True)
    print("=======================================================", flush=True)
    rec = results["recommendation"]
    print(f"* Best Overall Model : {rec['bestOverallModel']}")
    print(f"* Best Local Model   : {rec['bestLocalModel']}")
    print(f"* Fastest Model      : {rec['fastestModel']}")
    print(f"* Safest Model       : {rec['safestModel']}")
    print("\nGemini Cloud Cost Projections (at ~15 form fields / app):")
    cost = rec["costProjections"]
    print(f"- 100 applications   : {cost['costPer100Apps']}")
    print(f"- 1,000 applications : {cost['costPer1000Apps']}")
    print(f"- 10,000 applications: {cost['costPer1000Apps']}")
    print("\nResults successfully saved to data/benchmark_results.json\n", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
