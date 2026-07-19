"use client";

import React, { useState, useEffect } from "react";
import { Accomplishment } from "../types";

interface FocusModeProps {
  isOpen: boolean;
  onClose: () => void;
  accomplishment: Accomplishment;
  onSaveAnswer: (qId: string, answer: string) => Promise<void>;
}

export function FocusMode({ isOpen, onClose, accomplishment, onSaveAnswer }: FocusModeProps) {
  const [activeQuestionIdx, setActiveQuestionIdx] = useState(0);
  const [answerInput, setAnswerInput] = useState("");
  const [saving, setSaving] = useState(false);

  const questions = accomplishment.missingQuestions || [];
  const currentQ = questions[activeQuestionIdx];

  useEffect(() => {
    if (currentQ) {
      setAnswerInput(currentQ.answer || "");
    }
  }, [activeQuestionIdx, currentQ]);

  if (!isOpen || !currentQ) return null;

  const handleSave = async () => {
    setSaving(true);
    await onSaveAnswer(currentQ.id, answerInput);
    setSaving(false);
    if (activeQuestionIdx < questions.length - 1) {
      setActiveQuestionIdx(prev => prev + 1);
    } else {
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950 p-6 overflow-y-auto">
      <div className="w-full max-w-2xl flex flex-col gap-6 p-8 rounded-2xl border border-slate-800 bg-slate-900 shadow-2xl">
        {/* Header */}
        <div className="flex justify-between items-center border-b border-slate-800 pb-3">
          <div>
            <span className="text-[10px] font-bold text-violet-400 uppercase tracking-widest">Focus Mode</span>
            <h3 className="text-sm font-bold text-slate-200 mt-1">{accomplishment.project} ({accomplishment.company})</h3>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-white text-xs font-bold">
            ✕ Exit Focus
          </button>
        </div>

        {/* Current Bullet text */}
        <div className="p-4 rounded-xl bg-slate-950 border border-slate-850 text-xs">
          <span className="text-[10px] font-bold text-slate-500 uppercase block mb-1">Current Accomplishment Context</span>
          <p className="text-slate-300 italic">"{accomplishment.problemContext?.what || accomplishment.resumeEvolution?.current}"</p>
        </div>

        {/* Gap Question card */}
        <div className="flex flex-col gap-3">
          <div className="flex justify-between items-center text-xs">
            <span className="text-[10px] font-black text-amber-400 uppercase tracking-wide bg-amber-950/40 px-2 py-0.5 rounded border border-amber-900/20">
              Priority Gap: {currentQ.category}
            </span>
            <span className="text-slate-500 font-semibold">{activeQuestionIdx + 1} of {questions.length}</span>
          </div>
          <h4 className="text-base font-bold text-slate-100">"{currentQ.question}"</h4>
          
          <textarea
            rows={6}
            value={answerInput}
            onChange={(e) => setAnswerInput(e.target.value)}
            placeholder="Provide architectural decisions, tradeoffs, metrics, or details to answer this gap..."
            className="w-full p-4 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none resize-none"
          />
        </div>

        {/* Action Controls */}
        <div className="flex justify-between items-center mt-4">
          <button
            onClick={() => {
              if (activeQuestionIdx < questions.length - 1) {
                setActiveQuestionIdx(prev => prev + 1);
              } else {
                onClose();
              }
            }}
            className="text-slate-500 hover:text-slate-300 text-xs font-bold"
          >
            Skip Question
          </button>
          
          <div className="flex gap-3">
            <button
              onClick={handleSave}
              disabled={saving || !answerInput.trim()}
              className="px-6 py-2.5 rounded-xl bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white font-bold text-xs transition"
            >
              {saving ? "Saving..." : "Save & Continue"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
