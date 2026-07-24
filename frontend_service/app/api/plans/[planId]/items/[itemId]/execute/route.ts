import { NextRequest, NextResponse } from "next/server";

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
      `http://backend:8081/plans/${planId}/items/${itemId}/execute`,
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
