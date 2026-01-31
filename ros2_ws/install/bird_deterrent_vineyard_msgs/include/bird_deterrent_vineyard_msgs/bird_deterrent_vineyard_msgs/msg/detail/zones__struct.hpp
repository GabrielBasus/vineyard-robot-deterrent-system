// generated from rosidl_generator_cpp/resource/idl__struct.hpp.em
// with input from bird_deterrent_vineyard_msgs:msg/Zones.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONES__STRUCT_HPP_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONES__STRUCT_HPP_

#include <algorithm>
#include <array>
#include <memory>
#include <string>
#include <vector>

#include "rosidl_runtime_cpp/bounded_vector.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


// Include directives for member types
// Member 'zones'
#include "bird_deterrent_vineyard_msgs/msg/detail/zone__struct.hpp"

#ifndef _WIN32
# define DEPRECATED__bird_deterrent_vineyard_msgs__msg__Zones __attribute__((deprecated))
#else
# define DEPRECATED__bird_deterrent_vineyard_msgs__msg__Zones __declspec(deprecated)
#endif

namespace bird_deterrent_vineyard_msgs
{

namespace msg
{

// message struct
template<class ContainerAllocator>
struct Zones_
{
  using Type = Zones_<ContainerAllocator>;

  explicit Zones_(rosidl_runtime_cpp::MessageInitialization _init = rosidl_runtime_cpp::MessageInitialization::ALL)
  {
    if (rosidl_runtime_cpp::MessageInitialization::ALL == _init ||
      rosidl_runtime_cpp::MessageInitialization::ZERO == _init)
    {
      this->t = 0.0;
    }
  }

  explicit Zones_(const ContainerAllocator & _alloc, rosidl_runtime_cpp::MessageInitialization _init = rosidl_runtime_cpp::MessageInitialization::ALL)
  {
    (void)_alloc;
    if (rosidl_runtime_cpp::MessageInitialization::ALL == _init ||
      rosidl_runtime_cpp::MessageInitialization::ZERO == _init)
    {
      this->t = 0.0;
    }
  }

  // field types and members
  using _t_type =
    double;
  _t_type t;
  using _zones_type =
    std::vector<bird_deterrent_vineyard_msgs::msg::Zone_<ContainerAllocator>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<bird_deterrent_vineyard_msgs::msg::Zone_<ContainerAllocator>>>;
  _zones_type zones;

  // setters for named parameter idiom
  Type & set__t(
    const double & _arg)
  {
    this->t = _arg;
    return *this;
  }
  Type & set__zones(
    const std::vector<bird_deterrent_vineyard_msgs::msg::Zone_<ContainerAllocator>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<bird_deterrent_vineyard_msgs::msg::Zone_<ContainerAllocator>>> & _arg)
  {
    this->zones = _arg;
    return *this;
  }

  // constant declarations

  // pointer types
  using RawPtr =
    bird_deterrent_vineyard_msgs::msg::Zones_<ContainerAllocator> *;
  using ConstRawPtr =
    const bird_deterrent_vineyard_msgs::msg::Zones_<ContainerAllocator> *;
  using SharedPtr =
    std::shared_ptr<bird_deterrent_vineyard_msgs::msg::Zones_<ContainerAllocator>>;
  using ConstSharedPtr =
    std::shared_ptr<bird_deterrent_vineyard_msgs::msg::Zones_<ContainerAllocator> const>;

  template<typename Deleter = std::default_delete<
      bird_deterrent_vineyard_msgs::msg::Zones_<ContainerAllocator>>>
  using UniquePtrWithDeleter =
    std::unique_ptr<bird_deterrent_vineyard_msgs::msg::Zones_<ContainerAllocator>, Deleter>;

  using UniquePtr = UniquePtrWithDeleter<>;

  template<typename Deleter = std::default_delete<
      bird_deterrent_vineyard_msgs::msg::Zones_<ContainerAllocator>>>
  using ConstUniquePtrWithDeleter =
    std::unique_ptr<bird_deterrent_vineyard_msgs::msg::Zones_<ContainerAllocator> const, Deleter>;
  using ConstUniquePtr = ConstUniquePtrWithDeleter<>;

  using WeakPtr =
    std::weak_ptr<bird_deterrent_vineyard_msgs::msg::Zones_<ContainerAllocator>>;
  using ConstWeakPtr =
    std::weak_ptr<bird_deterrent_vineyard_msgs::msg::Zones_<ContainerAllocator> const>;

  // pointer types similar to ROS 1, use SharedPtr / ConstSharedPtr instead
  // NOTE: Can't use 'using' here because GNU C++ can't parse attributes properly
  typedef DEPRECATED__bird_deterrent_vineyard_msgs__msg__Zones
    std::shared_ptr<bird_deterrent_vineyard_msgs::msg::Zones_<ContainerAllocator>>
    Ptr;
  typedef DEPRECATED__bird_deterrent_vineyard_msgs__msg__Zones
    std::shared_ptr<bird_deterrent_vineyard_msgs::msg::Zones_<ContainerAllocator> const>
    ConstPtr;

  // comparison operators
  bool operator==(const Zones_ & other) const
  {
    if (this->t != other.t) {
      return false;
    }
    if (this->zones != other.zones) {
      return false;
    }
    return true;
  }
  bool operator!=(const Zones_ & other) const
  {
    return !this->operator==(other);
  }
};  // struct Zones_

// alias to use template instance with default allocator
using Zones =
  bird_deterrent_vineyard_msgs::msg::Zones_<std::allocator<void>>;

// constant definitions

}  // namespace msg

}  // namespace bird_deterrent_vineyard_msgs

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONES__STRUCT_HPP_
