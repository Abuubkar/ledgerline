"use client";
// The queue opens on its newest case; J/K then walks it.
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Icon } from "@/components/Icon";
import { useLists } from "@/components/Lists";

export default function ExceptionsPage() {
  const { lists, load } = useLists();
  const router = useRouter();
  const list = lists.exceptions;
  useEffect(() => {
    (async () => {
      const loaded = list?.items.length ? list : await load("exceptions");
      if (loaded.items[0]) router.replace(`/exceptions/${loaded.items[0].id}`);
    })();
  }, []);
  if (list && !list.loading && !list.items.length) return <div className="page"><div className="empty"><Icon name="inbox" size={28} /><div>No exceptions. Every invoice is matched or waiting to be read.</div></div></div>;
  if (list?.error) return <div className="page"><div className="notice error"><Icon name="circle-x" /><div className="grow"><b>Couldn't load the queue</b>{list.error}</div></div></div>;
  return <div className="case"><div className="skeletons">{Array.from({ length: 5 }, (_, i) => <div key={i} className="skeleton" />)}</div></div>;
}
