import type { Metadata } from "next";
import { Suspense } from "react";
import { CheckoutPanel } from "@/components/checkout-panel";

export const metadata: Metadata = {
  title: "Checkout | SentinelPay",
};

type CheckoutPageProps = { params: Promise<{ paymentId: string }> };

async function CheckoutContent({ params }: CheckoutPageProps) {
  const { paymentId } = await params;
  return <CheckoutPanel reference={paymentId} />;
}

export default function CheckoutPage(props: CheckoutPageProps) {
  return (
    <Suspense fallback={<main className="checkout-shell"><section className="checkout-panel"><p className="eyebrow">SENTINELPAY CHECKOUT</p><h1>Loading checkout</h1></section></main>}>
      <CheckoutContent params={props.params} />
    </Suspense>
  );
}