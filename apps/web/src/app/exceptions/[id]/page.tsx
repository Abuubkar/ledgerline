import { CaseFile } from "@/components/CaseFile";
import { EnsureList } from "@/components/EnsureList";

export default async function ExceptionCase({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <><EnsureList list="exceptions" /><CaseFile id={id} /></>;
}
