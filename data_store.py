import csv
import json
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
INPUT_DIR = ROOT / "input" / "input"


def parse_datetime(value: str) -> Optional[datetime]:
    if value is None or value == "":
        return None
    value = value.strip()
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        # fallback for legacy CSV timestamps without timezone
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def parse_decimal(value: str) -> Decimal:
    if value is None or value == "":
        return Decimal("0.00")
    return Decimal(value)


@dataclass(frozen=True)
class CaseInput:
    case_id: str
    opened_at: Optional[datetime]
    language: str
    message: str
    claimed_order_id: str
    policy_version: str


@dataclass(frozen=True)
class OrderItem:
    order_id: str
    order_item_id: str
    product_id: str
    seller_id: str
    shipping_limit_date: Optional[datetime]
    price: Decimal
    freight_value: Decimal


@dataclass(frozen=True)
class OrderPayment:
    order_id: str
    payment_sequential: int
    payment_type: str
    payment_installments: int
    payment_value: Decimal


@dataclass(frozen=True)
class OrderReview:
    review_id: str
    order_id: str
    review_score: Optional[int]
    review_comment_title: str
    review_comment_message: str
    review_creation_date: Optional[datetime]
    review_answer_timestamp: Optional[datetime]


@dataclass(frozen=True)
class OrderRecord:
    order_id: str
    customer_id: str
    order_status: str
    order_purchase_timestamp: Optional[datetime]
    order_approved_at: Optional[datetime]
    order_delivered_carrier_date: Optional[datetime]
    order_delivered_customer_date: Optional[datetime]
    order_estimated_delivery_date: Optional[datetime]


@dataclass(frozen=True)
class OrderFacts:
    order_id: str
    order_status: str
    order_estimated_delivery_date: Optional[datetime]
    order_delivered_carrier_date: Optional[datetime]
    order_delivered_customer_date: Optional[datetime]
    total_item_value: Decimal
    total_freight_value: Decimal
    total_payment_value: Decimal
    payment_count: int
    item_count: int
    seller_ids: List[str]
    payment_sequential_ids: List[int]
    shipping_limit_dates: List[Optional[datetime]]
    order_items: List[OrderItem]
    order_payments: List[OrderPayment]
    order_reviews: List[OrderReview]


class DataStore:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else ROOT
        self.data_dir = self.root / "data"
        self.input_dir = self.root / "input" / "input"
        self._orders: Dict[str, OrderRecord] = {}
        self._items: Dict[str, List[OrderItem]] = {}
        self._payments: Dict[str, List[OrderPayment]] = {}
        self._reviews: Dict[str, List[OrderReview]] = {}
        self._customers: Dict[str, Dict[str, str]] = {}
        self._products: Dict[str, Dict[str, str]] = {}
        self._sellers: Dict[str, Dict[str, str]] = {}
        self._case_index: Dict[str, CaseInput] = {}
        self._load_all()

    def _load_all(self) -> None:
        self._load_orders()
        self._load_order_items()
        self._load_order_payments()
        self._load_order_reviews()
        self._load_customers()
        self._load_products()
        self._load_sellers()
        self._load_cases()

    def _load_csv_rows(self, file_path: Path) -> Sequence[Dict[str, str]]:
        with file_path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            return [row for row in reader]

    def _load_orders(self) -> None:
        for row in self._load_csv_rows(self.data_dir / "olist_orders_dataset.csv"):
            record = OrderRecord(
                order_id=row["order_id"],
                customer_id=row["customer_id"],
                order_status=row["order_status"],
                order_purchase_timestamp=parse_datetime(row.get("order_purchase_timestamp", "")),
                order_approved_at=parse_datetime(row.get("order_approved_at", "")),
                order_delivered_carrier_date=parse_datetime(row.get("order_delivered_carrier_date", "")),
                order_delivered_customer_date=parse_datetime(row.get("order_delivered_customer_date", "")),
                order_estimated_delivery_date=parse_datetime(row.get("order_estimated_delivery_date", "")),
            )
            self._orders[record.order_id] = record

    def _load_order_items(self) -> None:
        for row in self._load_csv_rows(self.data_dir / "olist_order_items_dataset.csv"):
            item = OrderItem(
                order_id=row["order_id"],
                order_item_id=row["order_item_id"],
                product_id=row["product_id"],
                seller_id=row["seller_id"],
                shipping_limit_date=parse_datetime(row.get("shipping_limit_date", "")),
                price=parse_decimal(row.get("price", "0")),
                freight_value=parse_decimal(row.get("freight_value", "0")),
            )
            self._items.setdefault(item.order_id, []).append(item)

    def _load_order_payments(self) -> None:
        for row in self._load_csv_rows(self.data_dir / "olist_order_payments_dataset.csv"):
            payment = OrderPayment(
                order_id=row["order_id"],
                payment_sequential=int(row["payment_sequential"]),
                payment_type=row["payment_type"],
                payment_installments=int(row["payment_installments"]),
                payment_value=parse_decimal(row.get("payment_value", "0")),
            )
            self._payments.setdefault(payment.order_id, []).append(payment)

    def _load_order_reviews(self) -> None:
        for row in self._load_csv_rows(self.data_dir / "olist_order_reviews_dataset.csv"):
            review = OrderReview(
                review_id=row["review_id"],
                order_id=row["order_id"],
                review_score=int(row["review_score"]) if row.get("review_score") else None,
                review_comment_title=row.get("review_comment_title", ""),
                review_comment_message=row.get("review_comment_message", ""),
                review_creation_date=parse_datetime(row.get("review_creation_date", "")),
                review_answer_timestamp=parse_datetime(row.get("review_answer_timestamp", "")),
            )
            self._reviews.setdefault(review.order_id, []).append(review)

    def _load_customers(self) -> None:
        for row in self._load_csv_rows(self.data_dir / "olist_customers_dataset.csv"):
            self._customers[row["customer_id"]] = row

    def _load_products(self) -> None:
        for row in self._load_csv_rows(self.data_dir / "olist_products_dataset.csv"):
            self._products[row["product_id"]] = row

    def _load_sellers(self) -> None:
        for row in self._load_csv_rows(self.data_dir / "olist_sellers_dataset.csv"):
            self._sellers[row["seller_id"]] = row

    def _load_cases(self) -> None:
        if not self.input_dir.exists():
            return
        for file_path in sorted(self.input_dir.glob("EC_*.json")):
            with file_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
                case = CaseInput(
                    case_id=payload["case_id"],
                    opened_at=parse_datetime(payload.get("opened_at", "")),
                    language=payload["customer_request"]["language"],
                    message=payload["customer_request"]["message"],
                    claimed_order_id=payload["customer_request"]["claimed_order_id"],
                    policy_version=payload.get("policy_version", ""),
                )
                self._case_index[case.case_id] = case

    def list_cases(self) -> List[str]:
        return sorted(self._case_index.keys())

    def load_case(self, case_id: str) -> CaseInput:
        if case_id not in self._case_index:
            raise KeyError(f"Case not found: {case_id}")
        return self._case_index[case_id]

    def load_order(self, order_id: str) -> OrderRecord:
        if order_id not in self._orders:
            raise KeyError(f"Order not found: {order_id}")
        return self._orders[order_id]

    def load_order_items(self, order_id: str) -> List[OrderItem]:
        return list(self._items.get(order_id, []))

    def load_order_payments(self, order_id: str) -> List[OrderPayment]:
        return list(self._payments.get(order_id, []))

    def load_order_reviews(self, order_id: str) -> List[OrderReview]:
        return list(self._reviews.get(order_id, []))

    def get_order_facts(self, order_id: str) -> OrderFacts:
        order = self.load_order(order_id)
        items = self.load_order_items(order_id)
        payments = self.load_order_payments(order_id)
        reviews = self.load_order_reviews(order_id)
        total_item_value = sum((item.price for item in items), Decimal("0.00"))
        total_freight_value = sum((item.freight_value for item in items), Decimal("0.00"))
        total_payment_value = sum((p.payment_value for p in payments), Decimal("0.00"))
        seller_ids = sorted({item.seller_id for item in items if item.seller_id})
        shipping_limit_dates = [item.shipping_limit_date for item in items]
        return OrderFacts(
            order_id=order.order_id,
            order_status=order.order_status,
            order_estimated_delivery_date=order.order_estimated_delivery_date,
            order_delivered_carrier_date=order.order_delivered_carrier_date,
            order_delivered_customer_date=order.order_delivered_customer_date,
            total_item_value=total_item_value,
            total_freight_value=total_freight_value,
            total_payment_value=total_payment_value,
            payment_count=len(payments),
            item_count=len(items),
            seller_ids=seller_ids,
            payment_sequential_ids=[p.payment_sequential for p in payments],
            shipping_limit_dates=shipping_limit_dates,
            order_items=items,
            order_payments=payments,
            order_reviews=reviews,
        )

    def get_case_order_data(self, case_id: str) -> Tuple[CaseInput, OrderFacts]:
        case = self.load_case(case_id)
        facts = self.get_order_facts(case.claimed_order_id)
        return case, facts

    def find_case_by_order(self, order_id: str) -> Optional[CaseInput]:
        for case in self._case_index.values():
            if case.claimed_order_id == order_id:
                return case
        return None

    def order_exists(self, order_id: str) -> bool:
        return order_id in self._orders


if __name__ == "__main__":
    store = DataStore()
    cases = store.list_cases()
    print(f"Loaded {len(cases)} input cases from {INPUT_DIR}")
    if cases:
        case_id = cases[0]
        case, facts = store.get_case_order_data(case_id)
        print(f"Sample case: {case.case_id} -> claimed order {case.claimed_order_id}")
        print(f"Order status: {facts.order_status}")
        print(f"Payment rows: {facts.payment_count}, total payment: {facts.total_payment_value}")
        print(f"Item rows: {facts.item_count}, total item: {facts.total_item_value}, freight: {facts.total_freight_value}")
