import { NextRequest } from 'next/server';
 
export function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  console.log("Extracted search parameters: " + searchParams);

  const query = searchParams.get('query'); // e.g. `/api/search?query=hello`
  console.log("Extracted query: " + query);

  return new Response(
    JSON.stringify({ result: `You searched for: ${query}` }),
    {
      headers: { 'Content-Type': 'application/json' },
    },
  );
}