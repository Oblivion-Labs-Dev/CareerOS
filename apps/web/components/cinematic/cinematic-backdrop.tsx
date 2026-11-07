"use client";

import { useEffect, useState } from "react";
import { useAtmosphere } from "@/hooks/use-atmosphere";

/** The painted trail in career-journey.webp, traced in the image's own pixels
 *  (2048x768). The image and the thread share one viewBox and one "slice"
 *  scaling, so the travelling light stays on the trail at every width. */
const TRAIL = "M 1330 745 C 1336 736, 1350 707, 1366 690 C 1382 673, 1406 658, 1423 642 C 1440 626, 1445 610, 1467 594 C 1489 578, 1520 562, 1556 546 C 1592 530, 1653 513, 1684 498 C 1715 483, 1734 467, 1740 455 C 1746 443, 1737 436, 1720 428 C 1703 420, 1669 413, 1640 405 C 1611 397, 1574 387, 1548 378 C 1522 369, 1490 358, 1482 350 C 1474 342, 1486 337, 1500 330 C 1514 323, 1541 316, 1564 306 C 1587 296, 1625 279, 1640 270 C 1655 261, 1659 256, 1655 250 C 1651 244, 1636 241, 1618 234 C 1600 227, 1560 216, 1545 210 C 1530 204, 1526 201, 1528 195 C 1530 189, 1546 182, 1560 175 C 1574 168, 1597 162, 1610 155 C 1623 148, 1638 145, 1640 135 C 1642 125, 1628 102, 1625 95";

export function CinematicBackdrop() {
  const [atmosphere] = useAtmosphere();
  const [pageHidden, setPageHidden] = useState(false);

  useEffect(() => {
    const syncVisibility = () => setPageHidden(document.visibilityState === "hidden");
    syncVisibility();
    document.addEventListener("visibilitychange", syncVisibility);
    return () => document.removeEventListener("visibilitychange", syncVisibility);
  }, []);

  if (atmosphere !== "cinematic") return null;

  return (
    <div className="cinematic-backdrop" aria-hidden="true" data-page-hidden={pageHidden}>
      <svg className="cinematic-scene" viewBox="0 0 2048 768" preserveAspectRatio="xMaxYMid slice">
        <defs>
          <filter id="career-thread-soften" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="4" />
          </filter>
        </defs>
        <image className="cinematic-scene-art" href="/cinematic/career-journey.webp" width="2048" height="768" />
        <path className="career-thread-glow" d={TRAIL} />
        <path className="career-thread-light" pathLength="1" d={TRAIL} />
      </svg>
    </div>
  );
}
