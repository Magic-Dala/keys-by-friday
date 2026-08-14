import Image from "next/image";

export function Brand() {
  return (
    <div className="brand" aria-label="Keys by Friday">
      <Image
        className="brandMark"
        src="/brand-mark.svg"
        width={44}
        height={44}
        alt=""
        aria-hidden="true"
        priority
      />
      <span className="brandCopy">
        <strong>Keys by Friday</strong>
        <span>Rental decision agent</span>
      </span>
    </div>
  );
}
