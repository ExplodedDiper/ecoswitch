async function analyze() {
    const input = document.getElementById("productInput").value;

    if (!input) {
        alert("Please enter a product name or URL.");
        return;
    }

    const response = await fetch("/analyze", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({ input })
    });

    const data = await response.json();

    const resultDiv = document.getElementById("result");

    if (data.error) {
        resultDiv.innerHTML = `<p style="color:red;">${data.error}</p>`;
        return;
    }

    let html = `
        <h3>Product Metrics</h3>
        <p><strong>Material:</strong> ${data.product_metrics.material || "-"}</p>
        <p><strong>Estimated CO₂:</strong> ${data.product_metrics.estimated_co2} kg</p>

        <h3>Greener Alternatives</h3>
    `;

    if (data.alternatives && data.alternatives.length > 0) {
        data.alternatives.forEach((alt, index) => {
            html += `
                <div style="margin-bottom: 20px;">
                    <h4>Option ${index + 1}</h4>
                    <p><strong>${alt.brand}</strong></p>
                    <p>${alt.product_name}</p>
                    <p>Material: ${alt.material}</p>
                    <p>Estimated CO₂: ${alt.estimated_co2} kg</p>
                    <p><em>${alt.why_lower_impact}</em></p>
                    <hr>
                </div>
            `;
        });
    } else {
        html += `<p>No suitable alternatives found.</p>`;
    }

    html += `
        <h3>Your Eco Stats</h3>
        <p>Points: ${data.user.points}</p>
        <p>CO₂ Saved: ${data.user.co2_saved} kg</p>
        <p>Level: ${data.user.level}</p>
        <hr>
        <small>${data.disclaimer}</small>
    `;

    resultDiv.innerHTML = html;
}