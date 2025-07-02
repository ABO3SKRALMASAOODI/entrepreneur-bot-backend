import { useEffect } from 'react';

export default function PaddleCheckoutPage() {
  useEffect(() => {
    const script = document.createElement('script');
    script.src = 'https://cdn.paddle.com/paddle/v2/paddle.js';
    script.async = true;
    script.onload = () => {
      window.Paddle.Initialize({
        token: 'live_dcf6d3e20a0df8006f9462d419f' // Client-side token
      });

      const params = new URLSearchParams(window.location.search);
      const txnId = params.get('_ptxn');
      if (txnId) {
        window.Paddle.Checkout.open({ transactionId: txnId });
      }
    };
    document.body.appendChild(script);
  }, []);

  return (
    <div style={{ padding: '50px', textAlign: 'center' }}>
      <h1>Secure Checkout</h1>
      <p>Please wait while we prepare your checkout...</p>
    </div>
  );
}
