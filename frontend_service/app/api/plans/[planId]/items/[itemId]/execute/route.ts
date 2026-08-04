import { NextRequest, NextResponse } from "next/server";

// Matches every other proxy route in the app. This previously hardcoded the Docker service
// name, so the route only resolved inside compose and 500'd in local dev.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

export async function POST(
  req: NextRequest,
  context: {
    params: Promise<{
      planId: string;
      itemId: string;
    }>;
  }
) {
  const { planId, itemId } = await context.params;

  try {
    const token = req.headers.get("authorization");

    const response = await fetch(
      `${BACKEND_URL}/plans/${planId}/items/${itemId}/execute`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token
            ? {
                Authorization: token,
              }
            : {}),
        },
        body: JSON.stringify({}),
      }
    );

    const data = await response.json();

    return NextResponse.json(data, {
      status: response.status,
    });
  } catch (err) {
    console.error("Execute route error:", err);

    return NextResponse.json(
      {
        error: "Could not reach backend",
      },
      {
        status: 500,
      }
    );
  }
}
