"""
naming.py
Generates batch repository names from a prefix, quantity and format.
"""

FORMATS = ["Bai 1", "Bai_1", "bai-1", "bai1"]


def generate_names(prefix: str, quantity: int, fmt: str) -> list[str]:
    prefix = prefix.strip()
    if not prefix:
        raise ValueError("Tên bài không được để trống.")
    if quantity <= 0:
        raise ValueError("Số lượng phải lớn hơn 0.")
    if quantity > 1000:
        raise ValueError("Số lượng quá lớn (tối đa 1000 repository mỗi lần tạo).")

    names = []
    for i in range(1, quantity + 1):
        if fmt == "Bai 1":
            names.append(f"{prefix} {i}")
        elif fmt == "Bai_1":
            names.append(f"{prefix}_{i}")
        elif fmt == "bai-1":
            names.append(f"{prefix.lower()}-{i}")
        elif fmt == "bai1":
            names.append(f"{prefix.lower()}{i}")
        else:
            names.append(f"{prefix} {i}")
    return names
