import { redirect } from "next/navigation";

/** Applications merged into the dashboard — keep route for bookmarks. */
export default function ApplicationsPage() {
  redirect("/dashboard#applications");
}
