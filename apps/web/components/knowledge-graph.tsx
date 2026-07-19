"use client";

import React, { useState, useEffect, useRef } from "react";

interface Node {
  id: string;
  label: string;
  type: "accomplishment" | "concept" | "technology";
  x: number;
  y: number;
  vx: number;
  vy: number;
}

interface Link {
  source: string;
  target: string;
}

interface KnowledgeGraphProps {
  accomplishments: any[];
  onSelectAccomplishment?: (id: string) => void;
}

export function KnowledgeGraph({ accomplishments, onSelectAccomplishment }: KnowledgeGraphProps) {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [links, setLinks] = useState<Link[]>([]);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [draggedNode, setDraggedNode] = useState<string | null>(null);
  const [zoom, setZoom] = useState<number>(1);
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const containerRef = useRef<SVGSVGElement>(null);
  const isPanningRef = useRef<boolean>(false);
  const panStartRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  // Initialize nodes and links
  useEffect(() => {
    const newNodes: Node[] = [];
    const newLinks: Link[] = [];
    const nodeMap = new Map<string, boolean>();

    // Center coordinates
    const width = 800;
    const height = 500;

    accomplishments.forEach((acc, i) => {
      const accId = acc.id || `acc_${i}`;
      // Random position around the center
      const angle = (i / accomplishments.length) * Math.PI * 2;
      const radius = 120 + Math.random() * 50;
      
      newNodes.push({
        id: accId,
        label: acc.project || acc.company || "Accomplishment",
        type: "accomplishment",
        x: width / 2 + Math.cos(angle) * radius,
        y: height / 2 + Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
      });
      nodeMap.set(accId, true);

      // Add technology nodes
      const techStack = acc.techStack || [];
      techStack.forEach((tech: string, j: number) => {
        const techId = `tech_${tech.toLowerCase()}`;
        if (!nodeMap.has(techId)) {
          const techAngle = angle + (j + 1) * 0.3;
          newNodes.push({
            id: techId,
            label: tech,
            type: "technology",
            x: width / 2 + Math.cos(techAngle) * (radius + 100),
            y: height / 2 + Math.sin(techAngle) * (radius + 100),
            vx: 0,
            vy: 0,
          });
          nodeMap.set(techId, true);
        }
        newLinks.push({ source: accId, target: techId });
      });

      // Add concept nodes
      const concepts = acc.concepts || [];
      concepts.forEach((concept: string, k: number) => {
        const conceptId = `concept_${concept.toLowerCase()}`;
        if (!nodeMap.has(conceptId)) {
          const conceptAngle = angle - (k + 1) * 0.3;
          newNodes.push({
            id: conceptId,
            label: concept,
            type: "concept",
            x: width / 2 + Math.cos(conceptAngle) * (radius + 80),
            y: height / 2 + Math.sin(conceptAngle) * (radius + 80),
            vx: 0,
            vy: 0,
          });
          nodeMap.set(conceptId, true);
        }
        newLinks.push({ source: accId, target: conceptId });
      });
    });

    setNodes(newNodes);
    setLinks(newLinks);
  }, [accomplishments]);

  // Simple Physics simulation step (run standard force model)
  useEffect(() => {
    if (nodes.length === 0 || draggedNode !== null) return;

    const interval = setInterval(() => {
      setNodes((currentNodes) => {
        const nextNodes = currentNodes.map((n) => ({ ...n }));
        const width = 800;
        const height = 500;
        const center = { x: width / 2, y: height / 2 };

        // 1. Gravity force to center
        nextNodes.forEach((n) => {
          const dx = center.x - n.x;
          const dy = center.y - n.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          n.vx += (dx / dist) * 0.05;
          n.vy += (dy / dist) * 0.05;
        });

        // 2. Repulsion force between all nodes (prevent overlap)
        for (let i = 0; i < nextNodes.length; i++) {
          for (let j = i + 1; j < nextNodes.length; j++) {
            const n1 = nextNodes[i];
            const n2 = nextNodes[j];
            const dx = n2.x - n1.x;
            const dy = n2.y - n1.y;
            const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            const minDist = n1.type === "accomplishment" ? 90 : 60;

            if (dist < minDist) {
              const force = (minDist - dist) * 0.15;
              const fx = (dx / dist) * force;
              const fy = (dy / dist) * force;
              n1.vx -= fx;
              n1.vy -= fy;
              n2.vx += fx;
              n2.vy += fy;
            }
          }
        }

        // 3. Spring force along links
        links.forEach((link) => {
          const sourceNode = nextNodes.find((n) => n.id === link.source);
          const targetNode = nextNodes.find((n) => n.id === link.target);
          if (sourceNode && targetNode) {
            const dx = targetNode.x - sourceNode.x;
            const dy = targetNode.y - sourceNode.y;
            const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            const desiredDist = 110;
            const force = (dist - desiredDist) * 0.04;
            const fx = (dx / dist) * force;
            const fy = (dy / dist) * force;
            sourceNode.vx += fx;
            sourceNode.vy += fy;
            targetNode.vx -= fx;
            targetNode.vy -= fy;
          }
        });

        // Update positions with damping
        nextNodes.forEach((n) => {
          n.x += n.vx;
          n.y += n.vy;
          n.vx *= 0.85; // Damping
          n.vy *= 0.85;

          // Keep in bounds
          n.x = Math.max(50, Math.min(width - 50, n.x));
          n.y = Math.max(50, Math.min(height - 50, n.y));
        });

        return nextNodes;
      });
    }, 30);

    return () => clearInterval(interval);
  }, [nodes.length, links, draggedNode]);

  // Handle Dragging
  const handleMouseDown = (nodeId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setDraggedNode(nodeId);
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (draggedNode && containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      // Translate client coords using zoom/pan
      const clientX = (e.clientX - rect.left - pan.x) / zoom;
      const clientY = (e.clientY - rect.top - pan.y) / zoom;

      setNodes((curr) =>
        curr.map((n) =>
          n.id === draggedNode
            ? { ...n, x: clientX, y: clientY, vx: 0, vy: 0 }
            : n
        )
      );
    } else if (isPanningRef.current) {
      const dx = e.clientX - panStartRef.current.x;
      const dy = e.clientY - panStartRef.current.y;
      setPan({ x: pan.x + dx, y: pan.y + dy });
      panStartRef.current = { x: e.clientX, y: e.clientY };
    }
  };

  const handleMouseUp = () => {
    setDraggedNode(null);
    isPanningRef.current = false;
  };

  // Zoom controls
  const handleZoomIn = () => setZoom((z) => Math.min(z + 0.15, 2.5));
  const handleZoomOut = () => setZoom((z) => Math.max(z - 0.15, 0.4));
  const handleZoomReset = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  };

  // Check if nodes are connected
  const isConnected = (id1: string, id2: string) => {
    if (id1 === id2) return true;
    return links.some(
      (l) =>
        (l.source === id1 && l.target === id2) ||
        (l.source === id2 && l.target === id1)
    );
  };

  return (
    <div className="relative border border-arsenal-border rounded-xl bg-slate-950/70 overflow-hidden w-full h-[500px] select-none">
      {/* Zoom and pan controls */}
      <div className="absolute top-4 right-4 z-10 flex flex-col gap-1.5">
        <button
          onClick={handleZoomIn}
          className="w-8 h-8 rounded-lg bg-slate-900 border border-slate-800 text-slate-300 hover:text-white hover:bg-slate-800 transition flex items-center justify-center text-lg font-bold"
          title="Zoom In"
        >
          +
        </button>
        <button
          onClick={handleZoomOut}
          className="w-8 h-8 rounded-lg bg-slate-900 border border-slate-800 text-slate-300 hover:text-white hover:bg-slate-800 transition flex items-center justify-center text-lg font-bold"
          title="Zoom Out"
        >
          −
        </button>
        <button
          onClick={handleZoomReset}
          className="w-8 h-8 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-400 hover:text-white hover:bg-slate-800 transition flex items-center justify-center font-medium"
          title="Reset View"
        >
          Fit
        </button>
      </div>

      <div className="absolute top-4 left-4 text-xs font-semibold uppercase tracking-wider text-slate-400 bg-slate-900/60 backdrop-blur px-2.5 py-1 rounded-md border border-slate-800/40">
        Career Accomplishments Connection Graph
      </div>

      <svg
        ref={containerRef}
        className="w-full h-full cursor-grab active:cursor-grabbing"
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onMouseDown={(e) => {
          isPanningRef.current = true;
          panStartRef.current = { x: e.clientX, y: e.clientY };
        }}
      >
        <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
          {/* Link paths */}
          {links.map((link, idx) => {
            const sourceNode = nodes.find((n) => n.id === link.source);
            const targetNode = nodes.find((n) => n.id === link.target);
            if (!sourceNode || !targetNode) return null;

            const isDimmed =
              hoveredNode !== null &&
              !isConnected(hoveredNode, sourceNode.id) &&
              !isConnected(hoveredNode, targetNode.id);

            const isHighlighted =
              hoveredNode !== null &&
              (hoveredNode === sourceNode.id || hoveredNode === targetNode.id);

            return (
              <line
                key={`link-${idx}`}
                x1={sourceNode.x}
                y1={sourceNode.y}
                x2={targetNode.x}
                y2={targetNode.y}
                stroke={
                  isHighlighted
                    ? "rgba(139, 92, 246, 0.7)"
                    : "rgba(148, 163, 184, 0.15)"
                }
                strokeWidth={isHighlighted ? 2.5 : 1}
                opacity={isDimmed ? 0.25 : 1}
                strokeDasharray={
                  sourceNode.type === "accomplishment" &&
                  targetNode.type === "concept"
                    ? "4 4"
                    : undefined
                }
                className="transition-opacity duration-300"
              />
            );
          })}

          {/* Node items */}
          {nodes.map((node) => {
            const isDimmed =
              hoveredNode !== null && !isConnected(hoveredNode, node.id);
            const isHighlighted = hoveredNode === node.id;

            // Compute styling attributes based on type
            let color = "#ef4444"; // Accomplishment: Soft Red
            let radius = 16;
            let strokeColor = "rgba(239, 68, 68, 0.4)";

            if (node.type === "concept") {
              color = "#3b82f6"; // Concept: Blue
              radius = 10;
              strokeColor = "rgba(59, 130, 246, 0.4)";
            } else if (node.type === "technology") {
              color = "#10b981"; // Tech: Green/Emerald
              radius = 7;
              strokeColor = "rgba(16, 185, 129, 0.4)";
            }

            return (
              <g
                key={node.id}
                transform={`translate(${node.x}, ${node.y})`}
                onMouseEnter={() => setHoveredNode(node.id)}
                onMouseLeave={() => setHoveredNode(null)}
                className="cursor-pointer transition-all duration-300"
                opacity={isDimmed ? 0.35 : 1}
                onClick={(e) => {
                  e.stopPropagation();
                  if (node.type === "accomplishment" && onSelectAccomplishment) {
                    onSelectAccomplishment(node.id);
                  }
                }}
              >
                {/* Node halo/shadow */}
                <circle
                  r={radius + (isHighlighted ? 6 : 4)}
                  fill="transparent"
                  stroke={strokeColor}
                  strokeWidth={2}
                  className="animate-pulse"
                />

                {/* Main node sphere */}
                <circle
                  r={radius}
                  fill={color}
                  stroke="#020617"
                  strokeWidth={2.5}
                  onMouseDown={(e) => handleMouseDown(node.id, e)}
                />

                {/* Text Label */}
                <text
                  y={radius + 15}
                  textAnchor="middle"
                  fill={isHighlighted ? "#fff" : "#94a3b8"}
                  fontSize={
                    node.type === "accomplishment" ? "12px" : "10px"
                  }
                  fontWeight={
                    node.type === "accomplishment" ? "bold" : "normal"
                  }
                  className="pointer-events-none select-none drop-shadow"
                >
                  {node.label}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
