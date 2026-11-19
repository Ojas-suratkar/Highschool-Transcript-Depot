export async function calculateAdmissionReview(payload: any) {
  const response = await fetch("/api/admission/calculate", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
 
  if (!response.ok) {
    const errorText = await response.text();
 
    throw new Error(
      `Admission calculation failed: ${response.status} ${errorText}`
    );
  }
 
  return response.json();
}