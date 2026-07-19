"use client";

import React, { useState, useEffect } from "react";
import { Accomplishment } from "../types";

interface InterviewTabProps {
  accomplishments: Accomplishment[];
}

export function InterviewTab({ accomplishments }: InterviewTabProps) {
  const [prepMode, setPrepMode] = useState<"study" | "practice" | "mock" | "flashcard">("study");
  const [selectedAccId, setSelectedAccId] = useState<string>("all");
  const [activeQuestionIndex, setActiveQuestionIndex] = useState<number>(0);
  const [showAnswer, setShowAnswer] = useState<boolean>(false);
  const [timerSeconds, setTimerSeconds] = useState<number>(0);
  const [timerRunning, setTimerRunning] = useState<boolean>(false);
  const [notes, setNotes] = useState<string>("");

  // Compile list of prep questions from accomplishments
  const prepQuestions: { question: string; answer: string; project: string; category: string }[] = [];
  accomplishments.forEach((acc) => {
    if (selectedAccId !== "all" && acc.id !== selectedAccId) return;

    if (acc.interviewIntelligence) {
      acc.interviewIntelligence.recruiterPrep?.forEach((q) => {
        prepQuestions.push({ question: q.question, answer: q.answer, project: acc.project, category: "recruiter" });
      });
      acc.interviewIntelligence.hmPrep?.forEach((q) => {
        prepQuestions.push({ question: q.question, answer: q.idealAnswer, project: acc.project, category: "hiringManager" });
      });
      acc.interviewIntelligence.seniorPrep?.forEach((q) => {
        prepQuestions.push({ question: q.question, answer: q.answer, project: acc.project, category: "senior" });
      });
      acc.interviewIntelligence.staffPrep?.forEach((q) => {
        prepQuestions.push({ question: q.question, answer: q.idealAnswer, project: acc.project, category: "staff" });
      });
      acc.interviewIntelligence.principalPrep?.forEach((q) => {
        prepQuestions.push({ question: q.question, answer: q.expectedAnswer, project: acc.project, category: "principal" });
      });
    }
  });

  // Timer logic for Mock Mode
  useEffect(() => {
    let interval: any;
    if (timerRunning) {
      interval = setInterval(() => {
        setTimerSeconds((prev) => prev + 1);
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [timerRunning]);

  const handleStartMock = () => {
    setTimerSeconds(0);
    setTimerRunning(true);
    setShowAnswer(false);
  };

  const handleStopMock = () => {
    setTimerRunning(false);
  };

  const activeQuestion = prepQuestions[activeQuestionIndex];

  return (
    <div className="flex flex-col gap-6 animate-fade-in text-slate-100">
      <div className="flex flex-wrap justify-between items-center border-b border-slate-800 pb-3 gap-3">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Interview Readiness Center</h3>
          <p className="text-xs text-slate-500 mt-0.5">Mock and practice with AI-generated role-based queries.</p>
        </div>
        <div className="flex items-center gap-1.5 bg-slate-950 p-1 rounded-md border border-slate-800/80">
          {[
            { id: "study", label: "Study Mode" },
            { id: "practice", label: "Practice Mode" },
            { id: "mock", label: "Mock Sandbox" },
            { id: "flashcard", label: "Flashcards" },
          ].map((mode) => (
            <button
              key={mode.id}
              onClick={() => {
                setPrepMode(mode.id as any);
                setActiveQuestionIndex(0);
                setShowAnswer(false);
                setTimerRunning(false);
              }}
              className={`px-2.5 py-1 rounded text-[10px] font-bold capitalize transition ${
                prepMode === mode.id
                  ? "bg-slate-800 text-violet-400"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {mode.label}
            </button>
          ))}
        </div>
      </div>

      {/* Filter by Accomplishment dropdown */}
      <div className="flex items-center gap-2">
        <label className="text-[10px] font-bold text-slate-500 uppercase">Focus Accomplishment:</label>
        <select
          value={selectedAccId}
          onChange={(e) => {
            setSelectedAccId(e.target.value);
            setActiveQuestionIndex(0);
            setShowAnswer(false);
          }}
          className="bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs text-slate-300"
        >
          <option value="all">All Projects</option>
          {accomplishments.map((a) => (
            <option key={a.id} value={a.id}>{a.project}</option>
          ))}
        </select>
      </div>

      {prepQuestions.length === 0 ? (
        <div className="text-xs text-slate-500 italic py-12 text-center border border-slate-800 border-dashed rounded-lg">
          No prep questions compiled. Please verify that your accomplishments contain parsed Interview Prep blocks.
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Main workspace */}
          <div className="lg:col-span-8 flex flex-col gap-4">
            {prepMode === "study" && (
              <div className="flex flex-col gap-4">
                {prepQuestions.map((q, idx) => (
                  <div key={idx} className="p-5 rounded-xl border border-slate-800 bg-slate-900/10 flex flex-col gap-3">
                    <div className="flex justify-between items-center text-xs">
                      <span className="font-bold text-slate-300">Q: {q.question}</span>
                      <span className="text-[9px] font-bold uppercase tracking-wider text-violet-400 bg-slate-950 px-2 py-0.5 rounded border border-slate-800">{q.category}</span>
                    </div>
                    <p className="text-xs text-slate-200 bg-slate-950/50 p-3 rounded border border-slate-850 whitespace-pre-wrap leading-relaxed">
                      <strong>Answer:</strong> {q.answer}
                    </p>
                    <span className="text-[10px] text-slate-500 block font-medium">🎯 Project: {q.project}</span>
                  </div>
                ))}
              </div>
            )}

            {prepMode === "practice" && activeQuestion && (
              <div className="p-6 rounded-xl border border-slate-800 bg-slate-900/10 flex flex-col gap-4">
                <div className="flex justify-between items-center text-xs border-b border-slate-850 pb-2">
                  <span className="font-bold text-violet-400 uppercase tracking-widest">{activeQuestion.category} Level Prep</span>
                  <span className="text-slate-500 font-semibold">{activeQuestionIndex + 1} / {prepQuestions.length}</span>
                </div>
                <h4 className="text-sm font-bold text-white leading-normal">"{activeQuestion.question}"</h4>
                
                {showAnswer ? (
                  <div className="p-4 rounded-lg bg-slate-950 border border-slate-850 text-xs text-slate-200 leading-relaxed mt-2 animate-fade-in whitespace-pre-wrap">
                    <strong>Suggested Response outline:</strong>
                    <p className="mt-2 text-slate-300">{activeQuestion.answer}</p>
                  </div>
                ) : (
                  <button
                    onClick={() => setShowAnswer(true)}
                    className="w-full py-4 rounded-lg border border-slate-800 border-dashed text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-900/10 transition mt-2 font-bold"
                  >
                    Click to reveal suggested answer outline
                  </button>
                )}

                <div className="flex justify-between items-center mt-6 pt-4 border-t border-slate-850">
                  <button
                    disabled={activeQuestionIndex === 0}
                    onClick={() => {
                      setActiveQuestionIndex(p => p - 1);
                      setShowAnswer(false);
                    }}
                    className="px-3.5 py-1.5 rounded bg-slate-900 hover:bg-slate-800 disabled:opacity-30 text-xs"
                  >
                    Previous
                  </button>
                  <button
                    disabled={activeQuestionIndex === prepQuestions.length - 1}
                    onClick={() => {
                      setActiveQuestionIndex(p => p + 1);
                      setShowAnswer(false);
                    }}
                    className="px-3.5 py-1.5 rounded bg-violet-600 hover:bg-violet-500 font-semibold disabled:opacity-30 text-xs"
                  >
                    Next Question
                  </button>
                </div>
              </div>
            )}

            {prepMode === "mock" && activeQuestion && (
              <div className="p-6 rounded-xl border border-slate-800 bg-slate-900/10 flex flex-col gap-4">
                <div className="flex justify-between items-center border-b border-slate-850 pb-2.5">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-violet-400 uppercase tracking-widest">{activeQuestion.category}</span>
                    <span className="text-[10px] text-slate-500">Project: {activeQuestion.project}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-slate-300 bg-slate-950 px-2 py-0.5 rounded border border-slate-850">
                      {Math.floor(timerSeconds / 60)}:{(timerSeconds % 60).toString().padStart(2, "0")}
                    </span>
                    {timerRunning ? (
                      <button onClick={handleStopMock} className="text-[10px] bg-red-950/40 text-red-400 border border-red-900/20 px-2 py-0.5 rounded">Pause</button>
                    ) : (
                      <button onClick={handleStartMock} className="text-[10px] bg-violet-600 px-2 py-0.5 rounded text-white font-semibold">Start Timer</button>
                    )}
                  </div>
                </div>

                <h4 className="text-sm font-bold text-white">"{activeQuestion.question}"</h4>
                
                <div className="flex flex-col gap-2 mt-2">
                  <label className="text-[10px] font-bold text-slate-500 uppercase">Practice Session Notes</label>
                  <textarea
                    rows={6}
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Draft your response bullet points here or keep track of keywords..."
                    className="w-full p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none resize-none"
                  />
                </div>

                <div className="flex justify-between items-center mt-4">
                  <button
                    onClick={() => setShowAnswer(!showAnswer)}
                    className="text-xs text-violet-400 font-bold hover:underline"
                  >
                    {showAnswer ? "Hide Suggested Answer" : "Show Suggested Answer Reference"}
                  </button>
                  <div className="flex gap-2">
                    <button
                      disabled={activeQuestionIndex === 0}
                      onClick={() => {
                        setActiveQuestionIndex(p => p - 1);
                        setShowAnswer(false);
                        setNotes("");
                        setTimerSeconds(0);
                      }}
                      className="px-3 py-1 rounded bg-slate-900 text-xs"
                    >
                      Prev
                    </button>
                    <button
                      disabled={activeQuestionIndex === prepQuestions.length - 1}
                      onClick={() => {
                        setActiveQuestionIndex(p => p + 1);
                        setShowAnswer(false);
                        setNotes("");
                        setTimerSeconds(0);
                      }}
                      className="px-3.5 py-1 rounded bg-violet-600 text-white font-semibold text-xs"
                    >
                      Next
                    </button>
                  </div>
                </div>

                {showAnswer && (
                  <div className="p-4 rounded-lg bg-slate-950 border border-slate-850 text-xs text-slate-300 leading-relaxed mt-4 whitespace-pre-wrap animate-fade-in">
                    {activeQuestion.answer}
                  </div>
                )}
              </div>
            )}

            {prepMode === "flashcard" && activeQuestion && (
              <div className="flex flex-col items-center justify-center py-12">
                <div
                  onClick={() => setShowAnswer(!showAnswer)}
                  className="w-full max-w-sm h-64 rounded-xl border border-slate-800 bg-slate-900/20 hover:bg-slate-900/30 transition-all cursor-pointer p-6 flex flex-col justify-between text-center select-none shadow-xl transform active:scale-95"
                >
                  <span className="text-[9px] font-bold text-violet-400 uppercase tracking-widest">{activeQuestion.category}</span>
                  
                  <div className="flex items-center justify-center min-h-[120px]">
                    {showAnswer ? (
                      <p className="text-xs text-slate-200 leading-relaxed max-h-[120px] overflow-y-auto">{activeQuestion.answer}</p>
                    ) : (
                      <h4 className="text-sm font-bold text-white">"{activeQuestion.question}"</h4>
                    )}
                  </div>

                  <span className="text-[9px] text-slate-500 uppercase tracking-wider font-semibold">Click to flip card</span>
                </div>

                <div className="flex gap-4 mt-6">
                  <button
                    disabled={activeQuestionIndex === 0}
                    onClick={() => {
                      setActiveQuestionIndex(p => p - 1);
                      setShowAnswer(false);
                    }}
                    className="px-3.5 py-1 rounded bg-slate-900 text-xs"
                  >
                    Prev Card
                  </button>
                  <button
                    disabled={activeQuestionIndex === prepQuestions.length - 1}
                    onClick={() => {
                      setActiveQuestionIndex(p => p + 1);
                      setShowAnswer(false);
                    }}
                    className="px-3.5 py-1 rounded bg-violet-600 text-white font-semibold text-xs"
                  >
                    Next Card
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Right sidebar info */}
          <div className="lg:col-span-4 p-4 rounded-xl border border-slate-800 bg-slate-900/10 flex flex-col gap-4 text-xs">
            <h4 className="font-bold uppercase tracking-wider text-slate-400 border-b border-slate-800 pb-2">Practice Guidelines</h4>
            <div className="flex flex-col gap-2.5 text-slate-300">
              <p>• <strong>Study Mode</strong> displays everything together, suitable for initial review and outline memory mapping.</p>
              <p>• <strong>Practice Mode</strong> prompts you with questions sequentially to self-test response recall before checking validation keys.</p>
              <p>• <strong>Mock Sandbox</strong> simulates a live interviewing panel. Time your answers and write notes to review afterwards.</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
