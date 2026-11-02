/**
 * CareerOS UI primitives.
 *
 * Build pages from these rather than hand-rolling markup against global CSS —
 * that drift is what made each page feel like a different product. Every
 * primitive reads from the canonical tokens in globals.css, so anything
 * assembled from them is consistent by construction and theme-correct in both
 * light and dark.
 */

export { Button } from "./button";
export type { ButtonProps, ButtonSize, ButtonVariant } from "./button";

export { Card, CardBody, CardFooter, CardHeader, MetricCard } from "./card";
export type { CardPadding, CardProps, CardStatus, CardVariant } from "./card";

export { Input, SearchInput, Select, Textarea } from "./input";
export type { InputProps, SearchInputProps, SelectProps, TextareaProps } from "./input";

export { Badge, EmptyState, Skeleton, SkeletonText, Tabs } from "./feedback";
export type { BadgeProps, EmptyStateProps, SkeletonProps, StatusTone, TabItem } from "./feedback";
