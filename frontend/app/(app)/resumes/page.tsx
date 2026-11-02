import { redirect } from "next/navigation";

export default function ResumesRedirectPage() {
  redirect("/profile#documents");
}
