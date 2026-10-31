import { CaseFile } from "@/components/CaseFile";
import { EnsureList } from "@/components/EnsureList";

export default async function InvoiceCase({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <><EnsureList list="invoices" /><CaseFile id={id} /></>;
}
