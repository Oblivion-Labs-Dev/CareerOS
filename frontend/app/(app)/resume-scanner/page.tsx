import { redirect } from "next/navigation";

export default function ResumeScannerRedirectPage() {
  redirect("/profile#resume");
}
