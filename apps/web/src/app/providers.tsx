"use client";
import { useState, type ReactNode } from "react";
import { Provider } from "urql";
import { ListsProvider } from "@/components/Lists";
import { Shell } from "@/components/Shell";
import { makeClient } from "@/lib/client";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => makeClient());
  return <Provider value={client}><ListsProvider><Shell>{children}</Shell></ListsProvider></Provider>;
}
