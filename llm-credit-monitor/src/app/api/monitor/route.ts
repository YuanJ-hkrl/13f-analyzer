import { NextResponse } from "next/server";
import { collectMonitorSnapshot } from "@/lib/monitor";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  const snapshot = await collectMonitorSnapshot();
  return NextResponse.json(snapshot, {
    headers: {
      "Cache-Control": "no-store, max-age=0",
    },
  });
}
